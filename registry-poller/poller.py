import os
import requests
import time
from model_registry import ModelRegistry

# Read URLs from environment variables
model_registry_url = os.getenv("MODEL_REGISTRY_URL", "http://model-registry-service.kubeflow.svc.cluster.local:8080/api/model_registry/v1alpha3/registered_models")
event_listener_url = os.getenv("EVENT_LISTENER_URL", "http://el-model-registry-webhook.cansu.svc.cluster.local:8080")

# Initialize the ModelRegistry client
registry = ModelRegistry(
    server_address="model-registry-service.kubeflow.svc.cluster.local",
    port=9090,
    author="Tekton Pipeline",
    is_secure=False
)

# Initialize a dictionary to keep track of processed models and their latest versions and stages
processed_models = {}

# Function to get model registry data
def get_model_registry_data():
    response = requests.get(model_registry_url)
    if response.status_code == 200:
        return response.json().get('items', [])
    else:
        print(f"Failed to fetch model registry data: {response.status_code}")
        print(response.text)
        return []

# Function to get the latest version number and stage for a model based on lastUpdateTimeSinceEpoch
def get_latest_version(model_id):
    versions_url = f"{model_registry_url}/{model_id}/versions"
    response = requests.get(versions_url)
    if response.status_code == 200:
        versions = response.json().get('items', [])
        if versions:
            latest_version_entry = max(versions, key=lambda v: v.get('lastUpdateTimeSinceEpoch'))
            latest_version = latest_version_entry.get('name')
            stage = latest_version_entry.get('customProperties', {}).get('stage', {}).get('string_value', 'Unknown')
            return latest_version, stage
    else:
        print(f"Failed to fetch versions for model {model_id}: {response.status_code}")
        print(response.text)
    return None, None

# Function to get model artifact metadata
def get_model_metadata(name, version):
    model_artifact = registry.get_model_artifact(name, version)
    if model_artifact:
        return model_artifact.uri, model_artifact.model_format_name, model_artifact.model_format_version
    return None, None, None

# Function to trigger event listener if there's a new latest version with stage "prod"
def trigger_event_listener(name, owner, model_id, latest_version, stage, metadata):
    if stage.lower() == "prod":
        storage_uri, model_format_name, model_format_version = metadata
        payload = {
            "name": name,
            "owner": owner,
            "id": model_id,
            "latest_version": latest_version,
            "stage": stage,
            "storage_uri": storage_uri,
            "model_format_name": model_format_name,
            "model_format_version": model_format_version
        }
        headers = {
            'Content-Type': 'application/json'
        }
        response = requests.post(event_listener_url, headers=headers, json=payload)
        if response.status_code == 202:
            print(f"Successfully triggered event for model {name} with version {latest_version} and stage {stage}!")
        else:
            print(f"Failed to trigger event for model {name}: {response.status_code}")
            print(response.text)
    else:
        print(f"Stage for model {name} is not 'prod', skipping trigger.")

# Main polling loop
while True:
    print("Checking for new models and latest versions...")
    models = get_model_registry_data()
    
    for model in models:
        model_id = model.get('id')
        name = model.get('name')
        owner = model.get('owner')
        latest_version, stage = get_latest_version(model_id)
        
        if model_id not in processed_models:
            processed_models[model_id] = {"version": None, "stage": None}
        
        if latest_version and (processed_models[model_id]["version"] != latest_version or processed_models[model_id]["stage"] != stage):
            print(f"New version or stage change found for model {name}: {latest_version}, stage: {stage}")
            metadata = get_model_metadata(name, latest_version)
            if metadata:
                trigger_event_listener(name, owner, model_id, latest_version, stage, metadata)
                processed_models[model_id]["version"] = latest_version
                processed_models[model_id]["stage"] = stage
    
    print("Waiting for the next check...")
    time.sleep(5) 
