param(
    [Parameter(Mandatory=$true)][string]$AndroidPlayer
)
$ErrorActionPreference = 'Stop'
Push-Location $PSScriptRoot
try {
$env:JAVA_HOME = Join-Path $AndroidPlayer 'OpenJDK'
$env:PATH = "$env:JAVA_HOME/bin;$env:PATH"
$buildTools = Join-Path $AndroidPlayer 'SDK/build-tools/36.0.0'
$androidJar = Join-Path $AndroidPlayer 'SDK/platforms/android-34/android.jar'
function Check-Exit {
    if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }
}
New-Item -ItemType Directory -Force classes,dex | Out-Null
& "$env:JAVA_HOME/bin/javac.exe" -source 8 -target 8 -classpath $androidJar -d classes ProbeService.java DisplayPower.java
Check-Exit
& "$buildTools/d8.bat" --lib $androidJar --output dex (Get-ChildItem classes -Recurse -Filter '*.class' | Select-Object -ExpandProperty FullName)
Check-Exit
& "$buildTools/aapt2.exe" link -I $androidJar --manifest AndroidManifest.xml -o probe-unsigned.apk
Check-Exit
& "$env:JAVA_HOME/bin/jar.exe" uf probe-unsigned.apk -C dex classes.dex
Check-Exit
if (!(Test-Path probe.keystore)) {
    & "$env:JAVA_HOME/bin/keytool.exe" -genkeypair -keystore probe.keystore -storepass android -keypass android -alias monitor -dname 'CN=IMMENSIVA Monitor Diagnostic' -keyalg RSA -validity 3650 -noprompt
    Check-Exit
}
& "$buildTools/zipalign.exe" -f 4 probe-unsigned.apk probe-aligned.apk
Check-Exit
& "$buildTools/apksigner.bat" sign --ks probe.keystore --ks-pass pass:android --out monitor-probe.apk probe-aligned.apk
Check-Exit
& "$buildTools/d8.bat" --lib $androidJar --output display-control.jar classes/org/immensiva/monitorprobe/DisplayPower.class
Check-Exit
} finally {
    Pop-Location
}
