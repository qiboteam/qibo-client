USER_SCHEMA = {
    "type": "object",
    "properties": {"email": {"type": "string", "format": "email"}},
    "required": ["email"],
}

PARTITION_SCHEMA = {
    "type": "object",
    "properties": {
        "name": {"type": "string"},
        "max_num_qubits": {"type": "number"},
        "hardware_type": {
            "type": "string",
            "enum": [
                "simulator",
                "hardware",
            ],
        },
        "description": {"type": "string"},
        "status": {
            "type": "string",
            "enum": [
                "available",
                "unavailable",
            ],
        },
    },
    "required": ["name", "max_num_qubits", "hardware_type", "description", "status"],
}

PROJECTQUOTA_SCHEMA = {
    "type": "object",
    "properties": {
        "id": {"type": "integer"},
        "partition": PARTITION_SCHEMA,
        "max_num_shots": {"type": "integer"},
        "max_walltime_seconds": {"type": "number"},
        "seconds_left": {"type": "number"},
        "seconds_max": {"type": "number"},
        "shots_left": {"type": "number"},
        "shots_max": {"type": "number"},
        "jobs_left": {"type": "number"},
        "jobs_max": {"type": "number"},
        "prealloc_seconds": {"type": "number"},
        "prealloc_shots": {"type": "number"},
        "prealloc_jobs": {"type": "number"},
    },
    "required": [
        "id",
        "partition",
        "max_num_shots",
        "max_walltime_seconds",
        "seconds_left",
        "seconds_max",
        "shots_left",
        "shots_max",
        "jobs_left",
        "jobs_max",
        "prealloc_seconds",
        "prealloc_shots",
        "prealloc_jobs",
    ],
}

JOB_SCHEMA = {
    "type": "object",
    "properties": {
        "pid": {"type": "string"},
        "user": USER_SCHEMA,
        "projectquota": PROJECTQUOTA_SCHEMA,
        "circuit": {"type": ["string", "object"]},
        "transpiled_circuit": {"type": ["null", "string"]},
        "num_qubits": {"type": "integer"},
        "status": {
            "type": "string",
            "enum": [
                "queueing",
                "pending",
                "running",
                "postprocessing",
                "success",
                "ERROR",
            ],
        },
        "created_at": {"type": "string", "format": "date-time"},
        "updated_at": {"type": "string", "format": "date-time"},
        "result_path": {"type": "string"},
        "frequencies": {"type": ["null", "object"]},
        "nshots": {"type": "integer"},
        "stdout": {"type": "string"},
        "stderr": {"type": "string"},
        "qibo_version": {"type": ["null", "string"]},
        "qibolab_version": {"type": ["null", "string"]},
        "verbatim": {"type": "boolean"},
        "runtime": {"type": ["null", "number"]},
    },
    "required": [
        "pid",
        "user",
        "projectquota",
        "circuit",
        "status",
        "created_at",
        "updated_at",
    ],
}