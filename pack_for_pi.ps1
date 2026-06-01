$ErrorActionPreference = "Stop"
$src = "C:\Users\huyma\Desktop\ElderlyCareModel"
$out = "C:\Users\huyma\Desktop\elderly_care_deploy.zip"
$tmp = "C:\Users\huyma\Desktop\_deploy_staging"

Remove-Item -Recurse -Force $tmp -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $tmp | Out-Null

Write-Host "[1/5] Copy code..."
Copy-Item "$src\src" "$tmp\src" -Recurse
Copy-Item "$src\pipeline.py" "$tmp\"
Copy-Item "$src\requirements.txt" "$tmp\"
Copy-Item "$src\MODEL_NOTES.md" "$tmp\" -ErrorAction SilentlyContinue
Copy-Item "$src\deploy" "$tmp\deploy" -Recurse -ErrorAction SilentlyContinue

Write-Host "[2/5] Copy models (artifacts only)..."
Copy-Item "$src\models" "$tmp\models" -Recurse

Write-Host "[3/5] Strip training/eval modules + metrics PNG..."
$exclude = @(
    "$tmp\src\training",
    "$tmp\src\dataset_builders",
    "$tmp\src\evaluation",
    "$tmp\models\research",
    "$tmp\models\metrics\afdb_rhythm_eval_cache.npz"
)
foreach ($p in $exclude) {
    Remove-Item -Recurse -Force $p -ErrorAction SilentlyContinue
}
# Remove all PNG inside metrics (visual only, not needed at runtime)
Get-ChildItem -Recurse "$tmp\models\metrics" -Filter *.png -ErrorAction SilentlyContinue |
    Remove-Item -Force

Write-Host "[4/5] Clean __pycache__ ..."
Get-ChildItem -Recurse $tmp -Include "__pycache__","*.pyc" -Force -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force

Write-Host "[5/5] Compress..."
Remove-Item -Force $out -ErrorAction SilentlyContinue
Compress-Archive -Path "$tmp\*" -DestinationPath $out -CompressionLevel Optimal

$size = (Get-Item $out).Length / 1MB
Write-Host ""
Write-Host "Done. $out  ($([math]::Round($size,2)) MB)"
