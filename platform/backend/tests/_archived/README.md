# Archived Tests

This directory contains tests that have been archived because the features they test are not yet implemented or have been replaced by newer implementations.

## Directory Structure

- **`llm_tools/`** - Tests for LLM-based tool system (not yet implemented)
  - `test_action_flows.py` - Action flow integration tests (14 tests)
  - `test_user_scenarios.py` - User scenario integration tests (38 tests)
  - `test_action_handlers.py` - Action handler unit tests (9 tests)
  - **Total: ~61 tests**

- **`legacy_inference/`** - Tests for legacy inference system (replaced by Export/Deploy system)
  - `test_inference_pretrained.py` - Pretrained model inference tests
  - `test_inference_output_format.py` - Inference output format tests
  - **Total: ~4 tests**

- **`legacy_bugs/`** - Tests for specific bugs that have been resolved or are no longer relevant
  - `test_yolo11n_bug.py` - YOLO11n specific bug tests (5 tests)
  - **Total: ~5 tests**

## Why These Tests Are Archived

### LLM Tools (~61 tests)
These tests validate the LLM-based natural language tool system described in the Tool Registry design. The tool registry infrastructure exists (`app/utils/tool_registry.py`), but the action handler and flow execution layers are not yet implemented. These tests will be un-archived when:
- Action handlers for LLM tool calls are implemented
- Tool execution flows are integrated with the chat API
- Natural language intent parsing is connected to tool registry

**Related Files:**
- `app/utils/tool_registry.py` - Tool registry implementation (exists)
- `app/api/chat.py` - Chat API (LLM integration pending)
- Action handler layer (not yet implemented)

### Legacy Inference (~4 tests)
These tests were written for the old inference system that directly used training checkpoints. The platform has since adopted a more robust Export → Deploy workflow:
1. Training produces checkpoints
2. Export job converts to optimized format (ONNX, TensorRT, etc.)
3. Deployment creates inference endpoints

The new system is tested in `tests/e2e/test_export_deploy_e2e.py`.

**Replacement Tests:**
- `tests/e2e/test_export_deploy_e2e.py` - Complete export/deploy E2E tests
- `tests/integration/test_export_jobs.py` - Export job tests
- `tests/integration/test_deployments.py` - Deployment tests

### Legacy Bugs (~5 tests)
These tests were created to reproduce and validate fixes for specific bugs in YOLO11n training. The bugs have been resolved and the tests are no longer needed.

## When to Un-Archive

Tests can be moved back to the active test suite when:
1. The feature they test has been implemented
2. The tests are updated to match the current codebase structure
3. The tests pass with the current implementation

## Test Maintenance

Archived tests should be:
- Kept in version control for reference
- Not run as part of CI/CD pipeline
- Reviewed periodically to determine if they can be un-archived or deleted permanently

---

**Last Updated:** 2025-11-21
**Phase:** 4.5 Test Cleanup
