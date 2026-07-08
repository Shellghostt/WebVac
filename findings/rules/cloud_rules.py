"""Cloud asset exposure finding rules."""

CLOUD_RULES = [
    {
        "match": {"category": "cloud", "key": "s3_bucket"},
        "severity": "HIGH",
        "category": "cloud_exposure",
        "title_template": "S3 Bucket Reference in Client Code",
        "description_template": "S3 bucket URL found: {value} at {affected_url}.",
        "remediation": "Verify bucket ACLs and avoid hardcoding bucket names in client code.",
        "references": [],
    },
    {
        "match": {"category": "cloud", "key": "s3_uri"},
        "severity": "HIGH",
        "category": "cloud_exposure",
        "title_template": "S3 URI in Client Code",
        "description_template": "S3 URI found: {value} at {affected_url}.",
        "remediation": "Verify bucket permissions and access controls.",
        "references": [],
    },
    {
        "match": {"category": "cloud", "key": "azure_blob"},
        "severity": "HIGH",
        "category": "cloud_exposure",
        "title_template": "Azure Blob Storage Reference",
        "description_template": "Azure blob URL found: {value} at {affected_url}.",
        "remediation": "Review blob container access policies.",
        "references": [],
    },
    {
        "match": {"category": "cloud", "key": "gcs_bucket"},
        "severity": "HIGH",
        "category": "cloud_exposure",
        "title_template": "GCS Bucket Reference",
        "description_template": "GCS URL found: {value} at {affected_url}.",
        "remediation": "Review GCS bucket IAM permissions.",
        "references": [],
    },
]
