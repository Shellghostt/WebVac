"""
pipeline.py — Basic Item Pipeline for cleaning/validating data before storage.
"""

import importlib.util
import os
import sys

class PipelineManager:
    def __init__(self, pipeline_file: str = None):
        self.pipelines = []
        if pipeline_file and os.path.exists(pipeline_file):
            self._load_pipelines(pipeline_file)

    def _load_pipelines(self, filepath: str):
        """Dynamically load pipeline functions from a user-provided Python file."""
        module_name = "custom_pipeline"
        spec = importlib.util.spec_from_file_location(module_name, filepath)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            sys.modules[module_name] = module
            spec.loader.exec_module(module)

            # Look for a list named PIPELINES or just any callable named process_item
            if hasattr(module, "PIPELINES") and isinstance(module.PIPELINES, list):
                self.pipelines = module.PIPELINES
            elif hasattr(module, "process_item") and callable(module.process_item):
                self.pipelines = [module.process_item]

    def process_item(self, item: dict) -> dict:
        """Run the item through all loaded pipelines."""
        for pipeline in self.pipelines:
            item = pipeline(item)
            if item is None:
                # If a pipeline returns None, it means the item is dropped
                break
        return item
