param(
    [string]$OssutilPath = "D:\ossutil-2.3.0-windows-amd64-go1.20\ossutil-2.3.0-windows-amd64-go1.20\ossutil.exe",
    [string]$Bucket = "sen-illion",
    [string]$Prefix = "dn-eval-submissions",
    [string]$OutDir = "D:\human-eval-submissions"
)

if (!(Test-Path $OssutilPath)) {
    Write-Error "ossutil not found: $OssutilPath"
    exit 1
}

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$source = "oss://$Bucket/$Prefix"
& $OssutilPath cp -r $source $OutDir

Write-Host "Pulled submissions to: $OutDir"
