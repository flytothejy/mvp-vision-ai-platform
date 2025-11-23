# Kubernetes PVC Configuration

Persistent Volume Claims (PVC) for database storage in K8s deployment.

## Phase 11: Microservice Separation

### Database Architecture

```
Platform Service
    ↓
Platform DB (PostgreSQL)  ← platform-postgres-pvc (10Gi)
    - Projects, Datasets, Training Jobs, Experiments
    - Deployment, Export Jobs, Inference Jobs
    - Model Registry, Checkpoints

Labeler Service
    ↓
User DB (PostgreSQL)  ← user-postgres-pvc (5Gi)
    - Users, Organizations, Invitations
    - Project Members, Permissions
    - Shared across Platform + Labeler
```

## Storage Classes

### Cloud Providers

**AWS EKS:**
```yaml
storageClassName: gp3  # General Purpose SSD v3
# or
storageClassName: io2  # Provisioned IOPS SSD (high performance)
```

**GCP GKE:**
```yaml
storageClassName: pd-ssd  # SSD persistent disk
# or
storageClassName: pd-balanced  # Balanced persistent disk
```

**Azure AKS:**
```yaml
storageClassName: managed-premium  # Premium SSD
# or
storageClassName: managed  # Standard HDD
```

**Local/Kind:**
```yaml
storageClassName: standard  # Default local storage
```

## Deployment

### 1. Create PVCs

```bash
# Platform DB
kubectl apply -f platform-postgres-pvc.yaml

# User DB (Phase 11)
kubectl apply -f user-postgres-pvc.yaml
```

### 2. Verify PVCs

```bash
# Check PVC status
kubectl get pvc -n platform

# Expected output:
# NAME                    STATUS   VOLUME                CAPACITY   ACCESS MODES   STORAGECLASS   AGE
# platform-postgres-pvc   Bound    platform-postgres-pv   10Gi       RWO            standard       1m
# user-postgres-pvc       Bound    user-postgres-pv       5Gi        RWO            standard       1m
```

### 3. Use in Deployments

**Platform DB Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: platform-postgres
spec:
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: postgres-storage
          persistentVolumeClaim:
            claimName: platform-postgres-pvc
```

**User DB Deployment:**
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: user-postgres
spec:
  template:
    spec:
      containers:
        - name: postgres
          image: postgres:16
          volumeMounts:
            - name: postgres-storage
              mountPath: /var/lib/postgresql/data
      volumes:
        - name: postgres-storage
          persistentVolumeClaim:
            claimName: user-postgres-pvc
```

## Backup Strategy

### Automated Backups (Recommended)

**Velero:**
```bash
# Install Velero
velero install --provider aws --bucket platform-backups

# Create backup schedule
velero schedule create daily-backup \
  --schedule="0 2 * * *" \
  --include-namespaces platform

# Backup PVCs
velero backup create platform-db-backup \
  --include-resources pvc,pv \
  --selector app=platform-postgres
```

**PostgreSQL WAL Archiving:**
```yaml
# ConfigMap for PostgreSQL
apiVersion: v1
kind: ConfigMap
metadata:
  name: postgres-config
data:
  postgresql.conf: |
    wal_level = replica
    archive_mode = on
    archive_command = 'aws s3 cp %p s3://platform-backups/wal/%f'
```

### Manual Backups

```bash
# Platform DB
kubectl exec -n platform platform-postgres-0 -- \
  pg_dump -U admin platform > platform_backup_$(date +%Y%m%d).sql

# User DB
kubectl exec -n platform user-postgres-0 -- \
  pg_dump -U admin users > users_backup_$(date +%Y%m%d).sql
```

## Migration Path

### Tier Evolution

**Tier 1 (Local SQLite):**
```
shared_users.db (SQLite)
```

**Tier 2 (Local Docker PostgreSQL):**
```
postgres-user:5433 (PostgreSQL)
```

**Tier 3 (Railway PostgreSQL):**
```
USER_DATABASE_URL=postgresql://user:pass@railway.app:5432/railway
```

**Tier 4 (K8s PostgreSQL with PVC):**
```
user-postgres-pvc → StatefulSet → Service (user-postgres:5432)
```

## Monitoring

### PVC Usage

```bash
# Check PVC usage
kubectl exec -n platform platform-postgres-0 -- df -h /var/lib/postgresql/data

# Example output:
# Filesystem      Size  Used Avail Use% Mounted on
# /dev/sda1       10G   2.1G  7.9G  21% /var/lib/postgresql/data
```

### Alerts (Prometheus)

```yaml
# Alert when PVC usage > 80%
- alert: PVCHighUsage
  expr: kubelet_volume_stats_used_bytes / kubelet_volume_stats_capacity_bytes > 0.8
  labels:
    severity: warning
  annotations:
    summary: "PVC {{ $labels.persistentvolumeclaim }} usage > 80%"
```

## Resize PVC

```bash
# 1. Edit PVC
kubectl edit pvc platform-postgres-pvc -n platform

# 2. Update storage size
spec:
  resources:
    requests:
      storage: 20Gi  # Increased from 10Gi

# 3. Wait for resize
kubectl get pvc platform-postgres-pvc -n platform -w
```

**Note**: Requires StorageClass with `allowVolumeExpansion: true`

## Cleanup

```bash
# Delete PVC (data will be retained due to Retain policy)
kubectl delete pvc platform-postgres-pvc -n platform
kubectl delete pvc user-postgres-pvc -n platform

# Delete PV (CAUTION: This deletes data permanently)
kubectl delete pv platform-postgres-pv
kubectl delete pv user-postgres-pv
```

## Troubleshooting

### PVC Stuck in Pending

```bash
# Check events
kubectl describe pvc platform-postgres-pvc -n platform

# Common issues:
# 1. No available PV
# 2. StorageClass not found
# 3. Insufficient capacity
```

### PVC Bound but Pod Can't Mount

```bash
# Check node affinity
kubectl get pv platform-postgres-pv -o yaml | grep -A 5 nodeAffinity

# Check pod events
kubectl describe pod platform-postgres-0 -n platform
```

### Data Loss Prevention

1. **Always use Retain reclaim policy**
2. **Regular backups (automated preferred)**
3. **Test restore procedure**
4. **Monitor disk usage**
5. **Enable WAL archiving for PostgreSQL**
