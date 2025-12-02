#!/usr/bin/env python
"""
Unified Scenario Test Runner
Frontend request 기반 통합 테스트 실행기
"""
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


class ScenarioRunner:
    """시나리오 기반 테스트 실행"""

    def __init__(self, scenario_path: str, verbose: bool = False):
        self.scenario_path = Path(scenario_path)
        self.verbose = verbose
        self.variables: Dict[str, Any] = {}
        self.results: List[Dict] = []
        self.start_time = datetime.now()

        # Load scenario
        with open(self.scenario_path, encoding='utf-8') as f:
            self.scenario = json.load(f)

        # Create result directory
        timestamp = self.start_time.strftime("%Y%m%d_%H%M%S")
        scenario_name = self.scenario_path.stem
        self.result_dir = Path(__file__).parent / "results" / f"{timestamp}_{scenario_name}"
        self.result_dir.mkdir(parents=True, exist_ok=True)

        self.log(f"Scenario: {self.scenario['name']}")
        self.log(f"Description: {self.scenario['description']}")
        self.log(f"Result directory: {self.result_dir}")
        self.log("=" * 80)

    def log(self, message: str, level: str = "INFO"):
        """로그 출력"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{timestamp}] [{level}]"
        print(f"{prefix} {message}")

    def replace_variables(self, text: str) -> str:
        """변수 치환 {variable_name} → value"""
        if not isinstance(text, str):
            return text

        for key, value in self.variables.items():
            text = text.replace(f"{{{key}}}", str(value))
        return text

    def replace_in_dict(self, data: Dict) -> Dict:
        """딕셔너리 내 모든 변수 치환"""
        result = {}
        for key, value in data.items():
            if isinstance(value, str):
                result[key] = self.replace_variables(value)
            elif isinstance(value, dict):
                result[key] = self.replace_in_dict(value)
            elif isinstance(value, list):
                result[key] = [
                    self.replace_in_dict(item) if isinstance(item, dict)
                    else self.replace_variables(item) if isinstance(item, str)
                    else item
                    for item in value
                ]
            else:
                result[key] = value
        return result

    def extract_value(self, data: Any, path: str) -> Any:
        """JSONPath-like extraction (simple version)"""
        if path.startswith("$."):
            path = path[2:]

        keys = path.split(".")
        current = data

        for key in keys:
            if isinstance(current, dict):
                current = current.get(key)
            else:
                return None

        return current

    def execute_step(self, step: Dict) -> bool:
        """단일 스텝 실행"""
        step_num = step['step']
        step_name = step['name']
        self.log(f"Step {step_num}: {step_name}", "STEP")

        # Replace variables in URL, headers, data
        url = self.replace_variables(step['url'])
        headers = self.replace_in_dict(step.get('headers', {}))
        data = self.replace_in_dict(step.get('data', {})) if 'data' in step else None

        if self.verbose:
            self.log(f"  URL: {url}")
            self.log(f"  Method: {step['method']}")
            if headers:
                self.log(f"  Headers: {headers}")
            if data:
                self.log(f"  Data: {json.dumps(data, indent=2)}")

        # Execute request
        method = step['method'].lower()
        is_form_data = step.get('form_data', False)

        try:
            if method == 'get':
                response = requests.get(url, headers=headers)
            elif method == 'post':
                if data:
                    if is_form_data:
                        response = requests.post(url, headers=headers, data=data)
                    else:
                        response = requests.post(url, headers=headers, json=data)
                else:
                    response = requests.post(url, headers=headers)
            elif method == 'put':
                response = requests.put(url, headers=headers, json=data)
            elif method == 'delete':
                response = requests.delete(url, headers=headers)
            else:
                self.log(f"Unsupported method: {method}", "ERROR")
                return False

        except requests.RequestException as e:
            self.log(f"Request failed: {e}", "ERROR")
            return False

        # Check status
        expected_status = step.get('expected_status', 200)
        if response.status_code != expected_status:
            self.log(f"Status code mismatch: {response.status_code} != {expected_status}", "ERROR")
            self.log(f"Response: {response.text[:500]}", "ERROR")
            return False

        self.log(f"  Status: {response.status_code} OK", "OK")

        # Parse response
        try:
            response_data = response.json()
            if self.verbose:
                self.log(f"  Response: {json.dumps(response_data, indent=2)[:500]}")
        except ValueError:
            response_data = {"text": response.text}

        # Extract variables
        if 'extract' in step:
            for var_name, json_path in step['extract'].items():
                value = self.extract_value(response_data, json_path)
                if value is not None:
                    self.variables[var_name] = value
                    self.log(f"  Extracted {var_name} = {value}")
                else:
                    self.log(f"  Failed to extract {var_name} from {json_path}", "WARN")

        # Handle polling
        if 'poll' in step:
            poll_config = step['poll']
            interval = poll_config['interval']
            timeout = poll_config['timeout']
            until_status = poll_config['until_status']

            self.log(f"  Polling every {interval}s (timeout: {timeout}s)...")

            start = time.time()
            while time.time() - start < timeout:
                time.sleep(interval)

                # Poll request
                poll_response = requests.get(url, headers=headers)
                poll_data = poll_response.json()

                current_status = poll_data.get('status', 'unknown')
                self.log(f"  Status: {current_status}")

                if current_status in until_status:
                    self.log(f"  Reached terminal status: {current_status}")

                    # Check expected final status
                    expected_final = step.get('expected_final_status')
                    if expected_final and current_status != expected_final:
                        self.log(f"  Final status mismatch: {current_status} != {expected_final}", "ERROR")
                        return False

                    return True

            self.log(f"  Polling timeout after {timeout}s", "ERROR")
            return False

        # Save step result
        self.results.append({
            "step": step_num,
            "name": step_name,
            "status": "success",
            "response_status": response.status_code,
            "response": response_data
        })

        return True

    def validate_logs(self, config: Dict) -> bool:
        """로그 파일 검증"""
        log_file = Path(config['file'])
        if not log_file.exists():
            self.log(f"Log file not found: {log_file}", "WARN")
            return False

        log_content = log_file.read_text(encoding='utf-8', errors='ignore')

        required_patterns = config.get('required_patterns', [])
        for pattern in required_patterns:
            if not re.search(pattern, log_content):
                self.log(f"Pattern not found in logs: {pattern}", "ERROR")
                return False
            self.log(f"  Found pattern: {pattern}", "OK")

        return True

    def validate_cache(self, config: Dict) -> bool:
        """캐시 디렉토리 검증"""
        cache_path = Path(config['path'])
        if not cache_path.exists():
            self.log(f"Cache directory not found: {cache_path}", "ERROR")
            return False

        # TODO: 실제 캐시 파일 검증
        self.log(f"  Cache directory exists: {cache_path}", "OK")
        return True

    def run(self) -> bool:
        """시나리오 실행"""
        try:
            # Execute steps
            for step in self.scenario['steps']:
                success = self.execute_step(step)
                if not success:
                    self.log(f"Step {step['step']} failed", "ERROR")
                    return False

            # Validation
            if 'validation' in self.scenario:
                self.log("=" * 80)
                self.log("Running validations...", "VALIDATE")

                validation_config = self.scenario['validation']

                if 'subprocess_logs' in validation_config:
                    self.log("Validating subprocess logs...")
                    if not self.validate_logs(validation_config['subprocess_logs']):
                        return False

                if 'cache_directory' in validation_config:
                    self.log("Validating cache directory...")
                    if not self.validate_cache(validation_config['cache_directory']):
                        return False

            # Save results
            self.save_results()

            # Success
            duration = (datetime.now() - self.start_time).total_seconds()
            self.log("=" * 80)
            self.log(f"Scenario completed successfully in {duration:.1f}s", "SUCCESS")
            return True

        except Exception as e:
            self.log(f"Scenario failed: {e}", "ERROR")
            import traceback
            traceback.print_exc()
            return False

    def save_results(self):
        """결과 저장"""
        result_file = self.result_dir / "results.json"
        with open(result_file, 'w') as f:
            json.dump({
                "scenario": self.scenario['name'],
                "start_time": self.start_time.isoformat(),
                "end_time": datetime.now().isoformat(),
                "variables": self.variables,
                "results": self.results
            }, f, indent=2)
        self.log(f"Results saved to: {result_file}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python run_scenario.py <scenario_file.json> [--verbose]")
        print("\nExamples:")
        print("  python run_scenario.py scenarios/yolo_detection_mvtec.json")
        print("  python run_scenario.py scenarios/yolo_detection_mvtec.json --verbose")
        sys.exit(1)

    scenario_file = sys.argv[1]
    verbose = '--verbose' in sys.argv

    runner = ScenarioRunner(scenario_file, verbose=verbose)
    success = runner.run()

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
