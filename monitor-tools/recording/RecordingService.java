package org.immensiva.recording;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.ComponentName;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.SharedPreferences;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.util.Log;
import dalvik.system.PathClassLoader;
import java.lang.reflect.Method;
import java.io.BufferedReader;
import java.io.InputStreamReader;
import android.os.SystemClock;

/** Desired-state control. Check native state before invoking the Enterprise toggle once. */
public class RecordingService extends Service {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private String request;
    private String action;
    private boolean bound;
    private boolean finished;
    private SharedPreferences receipts;

    private String readState() throws Exception {
        Process process = new ProcessBuilder("/system/bin/getprop").redirectErrorStream(true).start();
        String value = null;
        boolean hasFlag = false;
        boolean verifiedFirmware = false;
        try (BufferedReader reader = new BufferedReader(new InputStreamReader(process.getInputStream()))) {
            String line;
            while ((line = reader.readLine()) != null) {
                if (line.startsWith("[pvr.screen.action]:")) hasFlag = true;
                if (line.equals("[ro.pui.build.version]: [5.15.7]")) verifiedFirmware = true;
                if (line.equals("[pvr.screen.action]: []")) value = "stopped";
                else if (line.equals("[pvr.screen.action]: [record]")) value = "recording";
            }
        }
        int exit = process.waitFor();
        if (exit == 0 && !hasFlag && verifiedFirmware
                && getPackageManager().getPackageInfo("com.bytedance.pico.screencapture", 0).versionCode == 100004072) {
            // This exact native recorder creates the flag only on its first start.
            value = "stopped";
        }
        if (exit != 0 || value == null) {
            throw new IllegalStateException("Native recording state unavailable; no toggle sent");
        }
        return value;
    }

    private String desiredState() { return "start".equals(action) ? "recording" : "stopped"; }

    private void confirmState(long sentAt) {
        if (finished) return;
        try {
            String state = readState();
            long elapsed = SystemClock.elapsedRealtime() - sentAt;
            // The native flag includes the recorder's startup countdown.
            if (elapsed >= 3000 && desiredState().equals(state)) {
                finish("STATE " + state + " CHANGED");
            } else if (elapsed >= 8000) {
                finish("FAILED Requested recording state was not reached; check the headset");
            } else {
                handler.postDelayed(() -> confirmState(sentAt), 250);
            }
        } catch (Exception error) {
            finish("FAILED Recording state could not be confirmed; check the headset");
        }
    }

    private void result(String id, String value) {
        Log.i("IMMENSIVA_RECORD", "RESULT " + id + " " + value.replace('\n', ' '));
    }

    private void finish(String value) {
        if (finished) return;
        finished = true;
        receipts.edit().putString("result", value).commit();
        result(request, value);
        stopSelf();
    }

    private final ServiceConnection connection = new ServiceConnection() {
        public void onServiceDisconnected(ComponentName name) {
            finish("FAILED PICO Enterprise service disconnected");
        }

        public void onServiceConnected(ComponentName name, IBinder binder) {
            if (finished) return;
            try {
                PathClassLoader vendor = new PathClassLoader(
                    "/system/priv-app/tobSettings/tobSettings.apk", getClassLoader());
                Class<?> stub = vendor.loadClass("com.pvr.tobservice.interfaces.IToBService$Stub");
                Object api = stub.getMethod("asInterface", IBinder.class).invoke(null, binder);
                Method record = api.getClass().getMethod("pbsRecord");
                record.setAccessible(true);
                if (desiredState().equals(readState())) {
                    finish("STATE " + desiredState() + " UNCHANGED");
                    return;
                }
                handler.removeCallbacksAndMessages(null);
                record.invoke(api);
                confirmState(SystemClock.elapsedRealtime());
            } catch (Exception error) {
                Throwable cause = error.getCause() == null ? error : error.getCause();
                finish("FAILED " + cause.toString());
            }
        }
    };

    public void onCreate() {
        super.onCreate();
        receipts = getSharedPreferences("recording-request", MODE_PRIVATE);
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(
            "recording-command", "IMMENSIVA recording control", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, new Notification.Builder(this, "recording-command")
            .setContentTitle("IMMENSIVA recording request")
            .setSmallIcon(android.R.drawable.ic_menu_camera).build());
    }

    public int onStartCommand(Intent intent, int flags, int startId) {
        String id = intent == null ? null : intent.getStringExtra("request");
        String requestedAction = intent == null ? null : intent.getStringExtra("action");
        if (id == null || !id.matches("[a-f0-9]{32}")
                || !("start".equals(requestedAction) || "stop".equals(requestedAction))) {
            if (request == null) stopSelf();
            return START_NOT_STICKY;
        }
        if (request != null) {
            if (!request.equals(id) || !requestedAction.equals(action)) result(id, "FAILED Another recording request is in progress");
            else if (finished) result(id, receipts.getString("result", "FAILED Check the headset"));
            return START_NOT_STICKY;
        }
        if (id.equals(receipts.getString("request", ""))) {
            result(id, requestedAction.equals(receipts.getString("action", ""))
                ? receipts.getString("result", "FAILED Previous request unconfirmed; check the headset")
                : "FAILED Request ID already used for another action");
            stopSelf();
            return START_NOT_STICKY;
        }
        if (System.currentTimeMillis() - receipts.getLong("at", 0) < 3000) {
            result(id, "FAILED Wait a few seconds for the current recording change to finish");
            stopSelf();
            return START_NOT_STICKY;
        }
        request = id;
        action = requestedAction;
        // Persist before calling the toggle, so redelivery after process death cannot toggle twice.
        if (!receipts.edit().putString("request", id).putString("action", action).putLong("at", System.currentTimeMillis())
                .putString("result", "FAILED Previous request unconfirmed; check the headset").commit()) {
            finish("FAILED Unable to save request receipt");
            return START_NOT_STICKY;
        }
        handler.postDelayed(() -> finish("FAILED PICO Enterprise service unavailable"), 5000);
        Intent service = new Intent("com.pvr.tobservice.remoteservice");
        service.setPackage("com.pvr.tobservice");
        try {
            bound = bindService(service, connection, BIND_AUTO_CREATE);
            if (!bound) finish("FAILED PICO Enterprise service unavailable");
        } catch (Exception error) {
            finish("FAILED " + error.toString());
        }
        return START_NOT_STICKY;
    }

    public IBinder onBind(Intent intent) { return null; }

    public void onDestroy() {
        finished = true;
        handler.removeCallbacksAndMessages(null);
        if (bound) unbindService(connection);
        super.onDestroy();
    }
}
