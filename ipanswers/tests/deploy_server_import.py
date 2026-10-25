from pathlib import Path
import importlib.util

def load_deployer():
    spec=importlib.util.spec_from_file_location('deploy_server',Path(__file__).resolve().parents[1]/'deploy-server.py')
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
