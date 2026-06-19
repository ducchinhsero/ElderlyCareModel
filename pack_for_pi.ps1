$ErrorActionPreference = "Stop"

$src = $PSScriptRoot
$out = Join-Path $src "elderly_care_deploy.zip"
$tmp = Join-Path $env:TEMP "elderly_care_deploy_staging"

$requiredArtifacts = @(
    # Model weights (.pkl)
    "models\stress\rf_model.pkl",
    "models\stress\svm_pipeline.pkl",
    "models\stress\scaler_final.pkl",
    "models\rhythm\rhythm_feature_model.pkl",
    "models\rhythm\rhythm_scaler.pkl",
    "models\ectopy\ectopy_feature_model.pkl",
    "models\ectopy\ectopy_scaler.pkl",
    "models\anomaly_legacy\isolation_forest_model.pkl",
    "models\anomaly_legacy\anomaly_scaler.pkl",
    # Schema / label / config JSON required at runtime (predictors validate
    # these strictly on load; missing one makes the model return "unknown").
    "models\stress\model_metadata.json",
    "models\stress\stress_feature_schema.json",
    "models\rhythm\rhythm_feature_schema.json",
    "models\rhythm\label_map.json",
    "models\rhythm\rhythm_decision_config.json",
    "models\ectopy\ectopy_feature_schema.json",
    "models\ectopy\label_map.json",
    "models\anomaly_legacy\anomaly_feature_schema.json"
)

foreach ($artifact in $requiredArtifacts) {
    $artifactPath = Join-Path $src $artifact
    if (-not (Test-Path $artifactPath)) {
        throw "Missing required runtime model artifact: $artifact"
    }
}

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp | Out-Null

Write-Host "[1/5] Copy code..."
Copy-Item "$src\src" "$tmp\src" -Recurse
Copy-Item "$src\pipeline.py" "$tmp\"
Copy-Item "$src\requirements.txt" "$tmp\"
Copy-Item "$src\.env.example" "$tmp\"
Copy-Item "$src\README.md" "$tmp\" -ErrorAction SilentlyContinue
Copy-Item "$src\MODEL_NOTES.md" "$tmp\" -ErrorAction SilentlyContinue
Copy-Item "$src\deploy" "$tmp\deploy" -Recurse -ErrorAction SilentlyContinue
Copy-Item "$src\docs" "$tmp\docs" -Recurse -ErrorAction SilentlyContinue
Copy-Item "$src\scripts" "$tmp\scripts" -Recurse -ErrorAction SilentlyContinue

Write-Host "[2/5] Copy models (artifacts only)..."
Copy-Item "$src\models" "$tmp\models" -Recurse

Write-Host "[3/5] Strip training/eval modules + research artifacts..."
$exclude = @(
    "$tmp\src\training",
    "$tmp\src\dataset_builders",
    "$tmp\src\evaluation",
    "$tmp\models\emotion",
    "$tmp\models\research",
    "$tmp\models\anomaly_legacy\random_forest_model.pkl",
    "$tmp\models\metrics\afdb_rhythm_eval_cache.npz"
)
foreach ($p in $exclude) {
    Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
}

Get-ChildItem -Recurse "$tmp\models\metrics" -Filter *.png -ErrorAction SilentlyContinue |
    Remove-Item -Force

Write-Host "[4/5] Clean caches..."
Get-ChildItem -Recurse $tmp -Include "__pycache__","*.pyc" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

Write-Host "[5/5] Compress..."
Remove-Item -Force $out -ErrorAction SilentlyContinue
Compress-Archive -Path "$tmp\*" -DestinationPath $out -CompressionLevel Optimal

$size = (Get-Item $out).Length / 1MB
Write-Host ""
Write-Host "Done. $out  ($([math]::Round($size,2)) MB)"
