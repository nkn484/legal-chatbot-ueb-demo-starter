[CmdletBinding()]
param(
    [string]$EnvFile = ".env"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function New-RandomBase64Secret {
    [byte[]]$bytes = New-Object byte[] 32
    $fillMethod = [System.Security.Cryptography.RandomNumberGenerator].GetMethod(
        "Fill",
        [System.Reflection.BindingFlags]::Public -bor [System.Reflection.BindingFlags]::Static,
        $null,
        [Type[]]@([byte[]]),
        $null
    )

    if ($null -ne $fillMethod) {
        [System.Security.Cryptography.RandomNumberGenerator]::Fill($bytes)
    }
    else {
        # Windows PowerShell on .NET Framework has no static Fill API.
        $generator = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        try {
            $generator.GetBytes($bytes)
        }
        finally {
            $generator.Dispose()
        }
    }

    return [Convert]::ToBase64String($bytes)
}

try {
    if ([string]::IsNullOrWhiteSpace($EnvFile)) {
        throw [System.ArgumentException]::new()
    }

    $targetPath = [System.IO.Path]::GetFullPath($EnvFile)
    $parentPath = [System.IO.Path]::GetDirectoryName($targetPath)
    $fileName = [System.IO.Path]::GetFileName($targetPath)
    if ([string]::IsNullOrWhiteSpace($parentPath) -or [string]::IsNullOrWhiteSpace($fileName)) {
        throw [System.ArgumentException]::new()
    }

    if (Test-Path -LiteralPath $parentPath) {
        if (-not (Test-Path -LiteralPath $parentPath -PathType Container)) {
            throw [System.IO.IOException]::new()
        }
    }
    else {
        $null = New-Item -ItemType Directory -Path $parentPath -Force
    }

    $targetKeys = @(
        "ZALO_OFFICIAL_BOT_WEBHOOK_SECRET",
        "CHANNEL_IDENTITY_HMAC_KEY"
    )
    $existingContent = ""
    if (Test-Path -LiteralPath $targetPath) {
        if (-not (Test-Path -LiteralPath $targetPath -PathType Leaf)) {
            throw [System.IO.IOException]::new()
        }
        $existingContent = [System.IO.File]::ReadAllText($targetPath)
        foreach ($key in $targetKeys) {
            $keyPattern = "(?m)^\s*" + [regex]::Escape($key) + "\s*="
            if ([regex]::IsMatch($existingContent, $keyPattern)) {
                throw [System.InvalidOperationException]::new()
            }
        }
    }

    $newLines = @()
    if ($existingContent.Length -gt 0 -and -not ($existingContent.EndsWith("`n") -or $existingContent.EndsWith("`r"))) {
        $newLines += ""
    }
    foreach ($key in $targetKeys) {
        $newLines += "{0}={1}" -f $key, (New-RandomBase64Secret)
    }

    $utf8 = [System.Text.UTF8Encoding]::new($false)
    [System.IO.File]::AppendAllLines($targetPath, [string[]]$newLines, $utf8)
}
catch {
    [System.Console]::Error.WriteLine("M08 secret setup failed.")
    exit 1
}
