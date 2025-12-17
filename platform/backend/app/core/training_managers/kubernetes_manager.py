"""
Kubernetes Training Manager

Phase 12: Temporal Orchestration & Backend Modernization

Manages training jobs by creating Kubernetes Jobs (Tier 1+).
This implementation is used when TRAINING_MODE=kubernetes.

Architecture:
- Job templates stored in ConfigMap (training-job-templates)
- Backend renders templates with Jinja2 and creates K8s Jobs
- Hybrid image versioning: default tag from _defaults + per-framework override
- Same Training Service code across all frameworks

Requirements:
- kubernetes Python client: pip install kubernetes
- jinja2: pip install jinja2
- pyyaml: pip install pyyaml
- Either in-cluster config (when running in K8s) or kubeconfig file
"""

import json
import logging
import os
import re
from datetime import datetime
from typing import Dict, Any, Optional, List

import yaml
from jinja2 import Template
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from app.core.training_manager import TrainingManager

logger = logging.getLogger(__name__)


# =============================================================================
# Default templates (fallback when ConfigMap is not available)
# =============================================================================
DEFAULT_BASE_TEMPLATE = """
apiVersion: batch/v1
kind: Job
metadata:
  name: "{{ job_name }}"
  namespace: "{{ namespace }}"
  labels:
    app: vision-ai-trainer
    managed-by: vision-ai-backend
    job-id: "{{ job_id }}"
    job-type: "{{ job_type }}"
    framework: "{{ framework }}"
spec:
  backoffLimit: {{ backoff_limit | default(2) }}
  ttlSecondsAfterFinished: {{ ttl_seconds | default(3600) }}
  activeDeadlineSeconds: {{ active_deadline | default(86400) }}
  template:
    metadata:
      labels:
        app: vision-ai-trainer
        job-id: "{{ job_id }}"
        job-type: "{{ job_type }}"
        framework: "{{ framework }}"
    spec:
      restartPolicy: Never
      serviceAccountName: {{ service_account | default('default') }}
      {% if image_pull_secret %}
      imagePullSecrets:
        - name: "{{ image_pull_secret }}"
      {% endif %}
      containers:
        - name: trainer
          image: "{{ image }}"
          imagePullPolicy: Always
          command: {{ command | tojson }}
          args: {{ args | tojson }}
          env:
            {% for key, value in env_vars.items() %}
            - name: "{{ key }}"
              value: {{ value | tojson }}
            {% endfor %}
            {% for env in extra_env %}
            - name: "{{ env.name }}"
              {% if env.value is defined %}
              value: {{ env.value | tojson }}
              {% elif env.valueFrom is defined %}
              valueFrom: {{ env.valueFrom | tojson }}
              {% endif %}
            {% endfor %}
          resources:
            requests:
              cpu: "{{ cpu_request | default('2') }}"
              memory: "{{ memory_request | default('8Gi') }}"
              {% if gpu_limit and gpu_limit != '0' %}
              nvidia.com/gpu: "{{ gpu_limit }}"
              {% endif %}
            limits:
              cpu: "{{ cpu_limit | default('4') }}"
              memory: "{{ memory_limit | default('16Gi') }}"
              {% if gpu_limit and gpu_limit != '0' %}
              nvidia.com/gpu: "{{ gpu_limit }}"
              {% endif %}
          volumeMounts:
            - name: tmp
              mountPath: /tmp
            - name: workspace
              mountPath: /workspace
            {% for vm in extra_volume_mounts %}
            - name: "{{ vm.name }}"
              mountPath: "{{ vm.mountPath }}"
              {% if vm.readOnly is defined %}
              readOnly: {{ vm.readOnly | lower }}
              {% endif %}
            {% endfor %}
      volumes:
        - name: tmp
          emptyDir: {}
        - name: workspace
          emptyDir: {}
        {% for vol in extra_volumes %}
        - name: "{{ vol.name }}"
          {% if vol.emptyDir is defined %}
          emptyDir:
            {% if vol.emptyDir.sizeLimit is defined %}
            sizeLimit: "{{ vol.emptyDir.sizeLimit }}"
            {% endif %}
          {% elif vol.persistentVolumeClaim is defined %}
          persistentVolumeClaim:
            claimName: "{{ vol.persistentVolumeClaim.claimName }}"
            {% if vol.persistentVolumeClaim.readOnly is defined %}
            readOnly: {{ vol.persistentVolumeClaim.readOnly | lower }}
            {% endif %}
          {% elif vol.configMap is defined %}
          configMap:
            name: "{{ vol.configMap.name }}"
          {% elif vol.secret is defined %}
          secret:
            secretName: "{{ vol.secret.secretName }}"
          {% endif %}
        {% endfor %}
      tolerations:
        - key: "nvidia.com/gpu"
          operator: "Exists"
          effect: "NoSchedule"
      {% if node_selector %}
      nodeSelector: {{ node_selector | tojson }}
      {% endif %}
"""

DEFAULT_FRAMEWORKS_CONFIG = {
    "_defaults": {
        "registry": "ghcr.io/vision-ai",
        "default_tag": "latest",
        "image_pull_secret": "",
        "service_account": "training-job-sa",
        "namespace": "training",
        "gpu_limit": "1",
        "cpu_request": "2",
        "cpu_limit": "4",
        "memory_request": "8Gi",
        "memory_limit": "16Gi",
    },
    "ultralytics": {
        "image_suffix": "trainer-ultralytics",
        "memory_request": "8Gi",
        "memory_limit": "16Gi",
        "extra_env": [],
        "extra_volumes": [],
        "extra_volume_mounts": [],
    },
    "huggingface": {
        "image_suffix": "trainer-huggingface",
        "memory_request": "16Gi",
        "memory_limit": "32Gi",
        "extra_env": [
            {"name": "HF_HOME", "value": "/tmp/huggingface"},
            {"name": "TRANSFORMERS_CACHE", "value": "/tmp/huggingface/transformers"},
        ],
        "extra_volumes": [
            {"name": "hf-cache", "emptyDir": {"sizeLimit": "10Gi"}},
        ],
        "extra_volume_mounts": [
            {"name": "hf-cache", "mountPath": "/tmp/huggingface"},
        ],
    },
    "timm": {
        "image_suffix": "trainer-timm",
        "memory_request": "8Gi",
        "memory_limit": "16Gi",
        "extra_env": [],
        "extra_volumes": [],
        "extra_volume_mounts": [],
    },
    "custom": {
        "memory_request": "8Gi",
        "memory_limit": "16Gi",
        "extra_env": [],
        "extra_volumes": [],
        "extra_volume_mounts": [],
    },
}


class KubernetesTrainingManager(TrainingManager):
    """
    Manages training jobs via Kubernetes Jobs (Tier 1+).

    Features:
    - ConfigMap-based job templates (training-job-templates)
    - Hybrid image versioning: default tag + per-framework override
    - Jinja2 template rendering for flexible job configuration
    - Fallback to default templates when ConfigMap unavailable
    """

    def __init__(self):
        logger.info("[KubernetesTrainingManager] Initializing")

        # Load K8s configuration
        try:
            # Try in-cluster config first (when running inside K8s)
            config.load_incluster_config()
            logger.info("[KubernetesTrainingManager] Using in-cluster config")
            self._in_cluster = True
        except config.ConfigException:
            # Fall back to kubeconfig file (local development)
            try:
                config.load_kube_config()
                logger.info("[KubernetesTrainingManager] Using kubeconfig file")
                self._in_cluster = False
            except config.ConfigException as e:
                logger.error(f"[KubernetesTrainingManager] Failed to load K8s config: {e}")
                raise RuntimeError(
                    "Could not configure Kubernetes client. "
                    "Ensure you're running in a K8s cluster or have a valid kubeconfig."
                )

        # Initialize K8s API clients
        self.batch_api = client.BatchV1Api()
        self.core_api = client.CoreV1Api()

        # Configuration from environment (used as overrides/fallbacks)
        self.namespace = os.getenv("K8S_TRAINING_NAMESPACE", "training")
        self.configmap_name = os.getenv("JOB_TEMPLATES_CONFIGMAP", "training-job-templates")

        # Environment variable overrides (take precedence over ConfigMap)
        self._env_overrides = {
            "registry": os.getenv("DOCKER_REGISTRY"),
            "default_tag": os.getenv("TRAINER_IMAGE_TAG"),
            "image_pull_secret": os.getenv("IMAGE_PULL_SECRET"),
            "gpu_limit": os.getenv("TRAINER_GPU_LIMIT"),
            "cpu_request": os.getenv("TRAINER_CPU_REQUEST"),
            "cpu_limit": os.getenv("TRAINER_CPU_LIMIT"),
            "memory_request": os.getenv("TRAINER_MEMORY_REQUEST"),
            "memory_limit": os.getenv("TRAINER_MEMORY_LIMIT"),
        }
        # Remove None values
        self._env_overrides = {k: v for k, v in self._env_overrides.items() if v is not None}

        # Job settings
        self.job_ttl_seconds = int(os.getenv("JOB_TTL_SECONDS_AFTER_FINISHED", "3600"))
        self.job_active_deadline = int(os.getenv("JOB_ACTIVE_DEADLINE_SECONDS", "86400"))
        self.job_backoff_limit = int(os.getenv("JOB_BACKOFF_LIMIT", "2"))

        # Storage configuration for trainer pods
        self.storage_env_vars = [
            "EXTERNAL_STORAGE_ENDPOINT",
            "EXTERNAL_STORAGE_ACCESS_KEY",
            "EXTERNAL_STORAGE_SECRET_KEY",
            "EXTERNAL_BUCKET_DATASETS",
            "INTERNAL_STORAGE_ENDPOINT",
            "INTERNAL_STORAGE_ACCESS_KEY",
            "INTERNAL_STORAGE_SECRET_KEY",
            "INTERNAL_BUCKET_CHECKPOINTS",
        ]

        # Load job templates from ConfigMap
        self._load_job_templates()

        logger.info(f"[KubernetesTrainingManager] Namespace: {self.namespace}")
        logger.info(f"[KubernetesTrainingManager] ConfigMap: {self.configmap_name}")

    def _load_job_templates(self) -> None:
        """
        Load job templates from ConfigMap.
        Falls back to default templates if ConfigMap is not available.
        """
        try:
            cm = self.core_api.read_namespaced_config_map(
                name=self.configmap_name,
                namespace=self.namespace,
            )

            self.base_template = cm.data.get("base-job.yaml", DEFAULT_BASE_TEMPLATE)
            frameworks_yaml = cm.data.get("frameworks.yaml", "")
            self.frameworks_config = yaml.safe_load(frameworks_yaml) or DEFAULT_FRAMEWORKS_CONFIG

            logger.info(
                f"[KubernetesTrainingManager] Loaded templates from ConfigMap: {self.configmap_name}"
            )
            logger.info(
                f"[KubernetesTrainingManager] Available frameworks: "
                f"{[k for k in self.frameworks_config.keys() if not k.startswith('_')]}"
            )

        except ApiException as e:
            if e.status == 404:
                logger.warning(
                    f"[KubernetesTrainingManager] ConfigMap '{self.configmap_name}' not found, "
                    "using default templates"
                )
            else:
                logger.warning(
                    f"[KubernetesTrainingManager] Failed to load ConfigMap: {e}, "
                    "using default templates"
                )
            self._use_default_templates()

    def _use_default_templates(self) -> None:
        """Use built-in default templates as fallback."""
        self.base_template = DEFAULT_BASE_TEMPLATE
        self.frameworks_config = DEFAULT_FRAMEWORKS_CONFIG
        logger.info("[KubernetesTrainingManager] Using default built-in templates")

    def reload_templates(self) -> bool:
        """
        Reload templates from ConfigMap.
        Call this to pick up ConfigMap changes without restarting.

        Returns:
            True if reload succeeded, False otherwise
        """
        try:
            self._load_job_templates()
            return True
        except Exception as e:
            logger.error(f"[KubernetesTrainingManager] Failed to reload templates: {e}")
            return False

    def _get_defaults(self) -> Dict[str, Any]:
        """
        Get default configuration with environment overrides applied.

        Returns:
            Merged defaults dictionary
        """
        defaults = dict(self.frameworks_config.get("_defaults", {}))
        # Apply environment overrides
        defaults.update(self._env_overrides)
        return defaults

    def _get_framework_config(self, framework: str) -> Dict[str, Any]:
        """
        Get merged configuration for a framework.
        Priority: env overrides > framework config > _defaults

        Args:
            framework: Framework name (ultralytics, huggingface, timm, custom)

        Returns:
            Merged configuration dictionary
        """
        defaults = self._get_defaults()
        fw_config = dict(self.frameworks_config.get(framework, {}))

        # Merge: defaults <- fw_config <- env_overrides
        merged = {**defaults, **fw_config}

        # Ensure lists exist
        merged.setdefault("extra_env", [])
        merged.setdefault("extra_volumes", [])
        merged.setdefault("extra_volume_mounts", [])

        return merged

    def _get_image(self, framework: str, custom_docker_image: str = None) -> str:
        """
        Get Docker image for a framework using hybrid versioning.

        Priority:
        1. custom_docker_image (if provided)
        2. fw_config.image (full image path)
        3. registry/image_suffix:image_tag (per-framework tag)
        4. registry/image_suffix:default_tag (default tag)

        Args:
            framework: Framework name
            custom_docker_image: Custom image override (optional)

        Returns:
            Full Docker image URI
        """
        if custom_docker_image:
            return custom_docker_image

        fw_config = self._get_framework_config(framework)

        # Full image path takes precedence
        if "image" in fw_config and fw_config["image"]:
            return fw_config["image"]

        # Build from components
        registry = fw_config.get("registry", "ghcr.io/vision-ai")
        image_suffix = fw_config.get("image_suffix", f"trainer-{framework}")

        # Hybrid: per-framework tag > default tag
        tag = fw_config.get("image_tag") or fw_config.get("default_tag", "latest")

        return f"{registry}/{image_suffix}:{tag}"

    def _render_job_manifest(self, params: Dict[str, Any]) -> Dict[str, Any]:
        """
        Render job manifest from Jinja2 template.

        Args:
            params: Template parameters

        Returns:
            Parsed Job manifest as dictionary
        """
        template = Template(self.base_template)
        rendered_yaml = template.render(**params)
        return yaml.safe_load(rendered_yaml)

    def _generate_job_name(self, job_type: str, job_id: int) -> str:
        """
        Generate unique K8s Job name.

        Args:
            job_type: Type of job (training, eval, inference, export)
            job_id: Job ID

        Returns:
            K8s-compatible job name (e.g., training-123-a1b2c3)
        """
        import hashlib

        timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
        hash_suffix = hashlib.md5(f"{job_id}-{timestamp}".encode()).hexdigest()[:6]
        return f"{job_type}-{job_id}-{hash_suffix}"

    def _build_template_params(
        self,
        job_name: str,
        job_id: int,
        job_type: str,
        framework: str,
        image: str,
        env_vars: Dict[str, str],
        command: List[str] = None,
        args: List[str] = None,
    ) -> Dict[str, Any]:
        """
        Build parameters for template rendering.

        Args:
            job_name: K8s Job name
            job_id: Job ID
            job_type: Job type (training, evaluation, inference, export)
            framework: Framework name
            image: Docker image
            env_vars: Environment variables dict
            command: Container command
            args: Container arguments

        Returns:
            Template parameters dictionary
        """
        fw_config = self._get_framework_config(framework)

        return {
            # Job metadata
            "job_name": job_name,
            "job_id": str(job_id),
            "job_type": job_type,
            "framework": framework,
            "namespace": fw_config.get("namespace", self.namespace),
            # Container
            "image": image,
            "command": command or ["python"],
            "args": args or ["train.py"],
            "env_vars": env_vars,
            # Resources
            "cpu_request": fw_config.get("cpu_request", "2"),
            "cpu_limit": fw_config.get("cpu_limit", "4"),
            "memory_request": fw_config.get("memory_request", "8Gi"),
            "memory_limit": fw_config.get("memory_limit", "16Gi"),
            "gpu_limit": fw_config.get("gpu_limit", "1"),
            # Framework-specific
            "extra_env": fw_config.get("extra_env", []),
            "extra_volumes": fw_config.get("extra_volumes", []),
            "extra_volume_mounts": fw_config.get("extra_volume_mounts", []),
            # Infrastructure
            "service_account": fw_config.get("service_account", "default"),
            "image_pull_secret": fw_config.get("image_pull_secret", ""),
            "node_selector": fw_config.get("node_selector"),
            # Job settings
            "backoff_limit": self.job_backoff_limit,
            "ttl_seconds": self.job_ttl_seconds,
            "active_deadline": self.job_active_deadline,
        }

    async def start_training(
        self,
        job_id: int,
        framework: str,
        model_name: str,
        dataset_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
        snapshot_id: str = None,
        dataset_version_hash: str = None,
        custom_docker_image: str = None,
    ) -> Dict[str, Any]:
        """
        Start training by creating a K8s Job.

        Args:
            job_id: Training job ID
            framework: Framework name (ultralytics, timm, huggingface, custom)
            model_name: Model name to train
            dataset_s3_uri: S3 URI of dataset
            callback_url: Backend API callback URL
            config: Training configuration dictionary
            snapshot_id: Dataset snapshot ID (for caching)
            dataset_version_hash: Dataset version hash (for caching)
            custom_docker_image: Custom Docker image (for custom framework)

        Returns:
            Dict containing K8s job metadata
        """
        logger.info(f"[KubernetesTrainingManager] Starting training job {job_id}")
        logger.info(f"[KubernetesTrainingManager]   Framework: {framework}")
        logger.info(f"[KubernetesTrainingManager]   Model: {model_name}")

        try:
            # Generate job name and get image
            k8s_job_name = self._generate_job_name("training", job_id)
            image = self._get_image(framework, custom_docker_image)
            logger.info(f"[KubernetesTrainingManager]   Image: {image}")

            # Extract dataset_id from S3 URI
            dataset_id_match = re.search(r"/datasets/([^/]+)/?$", dataset_s3_uri)
            dataset_id = dataset_id_match.group(1) if dataset_id_match else ""

            # Build environment variables
            env_vars = {
                "JOB_ID": str(job_id),
                "CALLBACK_URL": callback_url,
                "MODEL_NAME": model_name,
                "TASK_TYPE": config.get("task", "detection"),
                "FRAMEWORK": framework,
                "DATASET_ID": dataset_id,
                "DATASET_S3_URI": dataset_s3_uri,
                "EPOCHS": str(config.get("epochs", 100)),
                "BATCH_SIZE": str(config.get("batch", 16)),
                "LEARNING_RATE": str(config.get("learning_rate", 0.01)),
                "IMGSZ": str(config.get("imgsz", 640)),
                "DEVICE": str(config.get("device", "0")),
            }

            # Dataset caching parameters
            if snapshot_id:
                env_vars["SNAPSHOT_ID"] = snapshot_id
            if dataset_version_hash:
                env_vars["DATASET_VERSION_HASH"] = dataset_version_hash

            # CONFIG JSON
            config_json = {
                "epochs": config.get("epochs", 100),
                "batch": config.get("batch", 16),
                "learning_rate": config.get("learning_rate", 0.01),
                "imgsz": config.get("imgsz", 640),
                "device": config.get("device", "0"),
                "advanced_config": config.get("advanced_config", {}),
                "primary_metric": config.get("primary_metric"),
                "primary_metric_mode": config.get("primary_metric_mode", "max"),
                "split_config": config.get("split_config"),
            }
            config_json = {k: v for k, v in config_json.items() if v is not None}
            env_vars["CONFIG"] = json.dumps(config_json)

            # Storage environment variables
            for var in self.storage_env_vars:
                if var in os.environ:
                    env_vars[var] = os.environ[var]

            # Build template params and render
            params = self._build_template_params(
                job_name=k8s_job_name,
                job_id=job_id,
                job_type="training",
                framework=framework,
                image=image,
                env_vars=env_vars,
                command=["python"],
                args=["train.py", "--log-level", "INFO"],
            )

            job_manifest = self._render_job_manifest(params)

            # Submit job to K8s
            created_job = self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest,
            )

            logger.info(
                f"[KubernetesTrainingManager] Job {job_id} created: "
                f"{created_job.metadata.name} in namespace {self.namespace}"
            )

            return {
                "job_id": job_id,
                "k8s_job_name": created_job.metadata.name,
                "k8s_namespace": self.namespace,
                "image": image,
                "status": "submitted",
                "created_at": created_job.metadata.creation_timestamp.isoformat()
                if created_job.metadata.creation_timestamp
                else datetime.utcnow().isoformat(),
            }

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] K8s API error: {e}")
            raise RuntimeError(f"Failed to create K8s job: {e.reason}")
        except Exception as e:
            logger.error(f"[KubernetesTrainingManager] Failed to start job {job_id}: {e}")
            raise

    async def start_evaluation(
        self,
        test_run_id: int,
        training_job_id: Optional[int],
        framework: str,
        checkpoint_s3_uri: str,
        dataset_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Start evaluation by creating a K8s Job."""
        logger.info(f"[KubernetesTrainingManager] Starting evaluation {test_run_id}")

        try:
            k8s_job_name = self._generate_job_name("eval", test_run_id)
            image = self._get_image(framework)

            env_vars = {
                "TEST_RUN_ID": str(test_run_id),
                "CHECKPOINT_S3_URI": checkpoint_s3_uri,
                "DATASET_S3_URI": dataset_s3_uri,
                "CALLBACK_URL": callback_url,
                "CONFIG": json.dumps(config),
            }

            if training_job_id:
                env_vars["TRAINING_JOB_ID"] = str(training_job_id)

            for var in self.storage_env_vars:
                if var in os.environ:
                    env_vars[var] = os.environ[var]

            params = self._build_template_params(
                job_name=k8s_job_name,
                job_id=test_run_id,
                job_type="evaluation",
                framework=framework,
                image=image,
                env_vars=env_vars,
                args=["evaluate.py", "--log-level", "INFO"],
            )

            job_manifest = self._render_job_manifest(params)

            created_job = self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest,
            )

            logger.info(
                f"[KubernetesTrainingManager] Evaluation job created: {created_job.metadata.name}"
            )

            return {
                "test_run_id": test_run_id,
                "k8s_job_name": created_job.metadata.name,
                "k8s_namespace": self.namespace,
                "status": "submitted",
            }

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] K8s API error: {e}")
            raise RuntimeError(f"Failed to create evaluation job: {e.reason}")

    async def start_inference(
        self,
        inference_job_id: int,
        training_job_id: Optional[int],
        framework: str,
        checkpoint_s3_uri: str,
        images_s3_uri: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Start inference by creating a K8s Job."""
        logger.info(f"[KubernetesTrainingManager] Starting inference {inference_job_id}")

        try:
            k8s_job_name = self._generate_job_name("inference", inference_job_id)
            image = self._get_image(framework)

            env_vars = {
                "INFERENCE_JOB_ID": str(inference_job_id),
                "CHECKPOINT_S3_URI": checkpoint_s3_uri,
                "IMAGES_S3_URI": images_s3_uri,
                "CALLBACK_URL": callback_url,
                "CONFIG": json.dumps(config),
            }

            if training_job_id:
                env_vars["TRAINING_JOB_ID"] = str(training_job_id)

            for var in self.storage_env_vars:
                if var in os.environ:
                    env_vars[var] = os.environ[var]

            params = self._build_template_params(
                job_name=k8s_job_name,
                job_id=inference_job_id,
                job_type="inference",
                framework=framework,
                image=image,
                env_vars=env_vars,
                args=["predict.py", "--log-level", "INFO"],
            )

            job_manifest = self._render_job_manifest(params)

            created_job = self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest,
            )

            logger.info(
                f"[KubernetesTrainingManager] Inference job created: {created_job.metadata.name}"
            )

            return {
                "inference_job_id": inference_job_id,
                "k8s_job_name": created_job.metadata.name,
                "k8s_namespace": self.namespace,
                "status": "submitted",
            }

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] K8s API error: {e}")
            raise RuntimeError(f"Failed to create inference job: {e.reason}")

    async def start_export(
        self,
        export_job_id: int,
        training_job_id: int,
        framework: str,
        checkpoint_s3_uri: str,
        export_format: str,
        callback_url: str,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Start model export by creating a K8s Job."""
        logger.info(
            f"[KubernetesTrainingManager] Starting export {export_job_id} "
            f"(format: {export_format})"
        )

        try:
            k8s_job_name = self._generate_job_name("export", export_job_id)
            image = self._get_image(framework)

            env_vars = {
                "EXPORT_JOB_ID": str(export_job_id),
                "TRAINING_JOB_ID": str(training_job_id),
                "CHECKPOINT_S3_URI": checkpoint_s3_uri,
                "EXPORT_FORMAT": export_format,
                "CALLBACK_URL": callback_url,
                "CONFIG": json.dumps(config),
            }

            for var in self.storage_env_vars:
                if var in os.environ:
                    env_vars[var] = os.environ[var]

            params = self._build_template_params(
                job_name=k8s_job_name,
                job_id=export_job_id,
                job_type="export",
                framework=framework,
                image=image,
                env_vars=env_vars,
                args=["export.py", "--log-level", "INFO"],
            )

            job_manifest = self._render_job_manifest(params)

            created_job = self.batch_api.create_namespaced_job(
                namespace=self.namespace,
                body=job_manifest,
            )

            logger.info(
                f"[KubernetesTrainingManager] Export job created: {created_job.metadata.name}"
            )

            return {
                "export_job_id": export_job_id,
                "k8s_job_name": created_job.metadata.name,
                "k8s_namespace": self.namespace,
                "export_format": export_format,
                "status": "submitted",
            }

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] K8s API error: {e}")
            raise RuntimeError(f"Failed to create export job: {e.reason}")

    def stop_training(self, job_id: int) -> bool:
        """Stop a running training job by deleting the K8s Job."""
        logger.info(f"[KubernetesTrainingManager] Stopping job {job_id}")

        try:
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace,
                label_selector=f"job-id={job_id},job-type=training",
            )

            if not jobs.items:
                logger.warning(
                    f"[KubernetesTrainingManager] No K8s job found for job_id {job_id}"
                )
                return False

            for job in jobs.items:
                logger.info(f"[KubernetesTrainingManager] Deleting job: {job.metadata.name}")
                self.batch_api.delete_namespaced_job(
                    name=job.metadata.name,
                    namespace=self.namespace,
                    body=client.V1DeleteOptions(propagation_policy="Foreground"),
                )

            logger.info(f"[KubernetesTrainingManager] Job {job_id} stopped")
            return True

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] Failed to stop job {job_id}: {e}")
            return False

    def get_training_status(self, job_id: int) -> Optional[Dict[str, Any]]:
        """Get status of a training job from K8s."""
        try:
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace,
                label_selector=f"job-id={job_id},job-type=training",
            )

            if not jobs.items:
                return None

            job = jobs.items[0]
            status = job.status

            if status.succeeded and status.succeeded > 0:
                state = "completed"
            elif status.failed and status.failed > 0:
                state = "failed"
            elif status.active and status.active > 0:
                state = "running"
            else:
                state = "pending"

            return {
                "job_id": job_id,
                "k8s_job_name": job.metadata.name,
                "status": state,
                "active": status.active or 0,
                "succeeded": status.succeeded or 0,
                "failed": status.failed or 0,
                "start_time": status.start_time.isoformat() if status.start_time else None,
                "completion_time": status.completion_time.isoformat()
                if status.completion_time
                else None,
            }

        except ApiException as e:
            logger.error(
                f"[KubernetesTrainingManager] Failed to get status for job {job_id}: {e}"
            )
            return None

    def cleanup_resources(self, job_id: int) -> None:
        """Clean up K8s resources for a job."""
        logger.info(f"[KubernetesTrainingManager] Cleaning up resources for job {job_id}")

        try:
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace,
                label_selector=f"job-id={job_id}",
            )

            for job in jobs.items:
                logger.info(f"[KubernetesTrainingManager] Deleting job: {job.metadata.name}")
                try:
                    self.batch_api.delete_namespaced_job(
                        name=job.metadata.name,
                        namespace=self.namespace,
                        body=client.V1DeleteOptions(propagation_policy="Foreground"),
                    )
                except ApiException as e:
                    if e.status != 404:
                        logger.warning(
                            f"[KubernetesTrainingManager] Failed to delete job "
                            f"{job.metadata.name}: {e}"
                        )

            logger.info(f"[KubernetesTrainingManager] Cleanup completed for job {job_id}")

        except ApiException as e:
            logger.error(f"[KubernetesTrainingManager] Failed to cleanup job {job_id}: {e}")

    def get_job_logs(
        self, job_id: int, job_type: str = "training", tail_lines: int = 100
    ) -> Optional[str]:
        """Get logs from a K8s Job's pod."""
        try:
            jobs = self.batch_api.list_namespaced_job(
                namespace=self.namespace,
                label_selector=f"job-id={job_id},job-type={job_type}",
            )

            if not jobs.items:
                return None

            job_name = jobs.items[0].metadata.name

            pods = self.core_api.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=f"job-name={job_name}",
            )

            if not pods.items:
                return None

            pod_name = pods.items[0].metadata.name

            logs = self.core_api.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                container="trainer",
                tail_lines=tail_lines,
            )

            return logs

        except ApiException as e:
            logger.error(
                f"[KubernetesTrainingManager] Failed to get logs for job {job_id}: {e}"
            )
            return None
