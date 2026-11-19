param(
    [Parameter(Mandatory=$true)][string]$AndroidPlayer
)
$ErrorActionPreference = 'Stop'
$java = Join-Path $AndroidPlayer 'OpenJDK/bin'
$buildTools = Join-Path $AndroidPlayer 'SDK/build-tools/36.0.0'
$androidJar = Join-Path $AndroidPlayer 'SDK/platforms/android-34/android.jar'
$env:JAVA_HOME = Join-Path $AndroidPlayer 'OpenJDK'
function Check-Exit {
    if ($LASTEXITCODE -ne 0) { throw "Build command failed with exit code $LASTEXITCODE" }
}
Push-Location $PSScriptRoot
try {
    # A fresh build directory avoids stale Java classes without deleting any existing build.
    $build = Join-Path 'recording-build' ([guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Force "$build/classes","$build/dex" | Out-Null
    & "$java/javac.exe" -source 8 -target 8 -classpath $androidJar -d "$build/classes" recording/RecordingService.java
    Check-Exit
    & "$buildTools/d8.bat" --lib $androidJar --output "$build/dex" (Get-ChildItem "$build/classes" -Recurse -Filter '*.class' | Select-Object -ExpandProperty FullName)
    Check-Exit
    & "$buildTools/aapt2.exe" link -I $androidJar --manifest recording/AndroidManifest.xml -o "$build/unsigned.apk"
    Check-Exit
    & "$java/jar.exe" uf "$build/unsigned.apk" -C "$build/dex" classes.dex
    Check-Exit
    if (!(Test-Path recording.keystore)) {
        & "$java/keytool.exe" -genkeypair -keystore recording.keystore -storepass android -keypass android -alias recording -dname 'CN=IMMENSIVA Recording Control' -keyalg RSA -validity 3650 -noprompt
        Check-Exit
    }
    & "$buildTools/zipalign.exe" -f 4 "$build/unsigned.apk" "$build/aligned.apk"
    Check-Exit
    & "$buildTools/apksigner.bat" sign --ks recording.keystore --ks-pass pass:android --out screen-recording.apk "$build/aligned.apk"
    Check-Exit
    & "$buildTools/apksigner.bat" verify screen-recording.apk
    Check-Exit
} finally {
    Pop-Location
}
