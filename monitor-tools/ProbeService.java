package org.immensiva.monitorprobe;

import android.app.*;
import android.os.*;
import android.content.*;
import android.util.Log;
import dalvik.system.PathClassLoader;
import java.lang.reflect.*;
import org.json.JSONObject;
import org.json.JSONArray;
import java.io.*;
import java.util.zip.GZIPInputStream;

public class ProbeService extends Service {
    private final Handler handler = new Handler(Looper.getMainLooper());
    private Object api;
    private ClassLoader vendor;
    private boolean bound;
    private int samples;
    private String runId;
    private String map = "{}";
    private JSONObject boundary = new JSONObject();
    private final ServiceConnection connection = new ServiceConnection() {
        public void onServiceDisconnected(ComponentName name) {
            api = null;
        }
        public void onServiceConnected(ComponentName name, IBinder binder) {
            try {
                vendor = new PathClassLoader(
                    "/system/priv-app/tobSettings/tobSettings.apk", getClassLoader());
                Class<?> stub = vendor.loadClass("com.pvr.tobservice.interfaces.IToBService$Stub");
                api = stub.getMethod("asInterface", IBinder.class).invoke(null, binder);
                sample();
            } catch (Exception error) {
                Log.e("IMMENSIVA_PROBE", "Binding diagnostic failed", error);
            }
        }
    };

    private Object jsonValue(Object value, int depth) throws Exception {
        if (value == null) return JSONObject.NULL;
        if (value instanceof Number || value instanceof Boolean || value instanceof String) return value;
        if (depth > 4) return String.valueOf(value);
        if (value.getClass().isArray()) {
            JSONArray array = new JSONArray();
            for (int i = 0; i < Array.getLength(value); i++) {
                array.put(jsonValue(Array.get(value, i), depth + 1));
            }
            return array;
        }
        JSONObject object = new JSONObject();
        for (Field field : value.getClass().getFields()) {
            if (!Modifier.isStatic(field.getModifiers())) {
                object.put(field.getName(), jsonValue(field.get(value), depth + 1));
            }
        }
        return object;
    }

    private JSONObject readBoundary() {
        JSONObject result = new JSONObject();
        try {
            Method read = api.getClass().getMethod(
                "pbsCommonMessageLocked", String.class, Bundle.class);
            read.setAccessible(true);
            Bundle bundle = (Bundle) read.invoke(api, "get_large_space_bounds_info", new Bundle());
            result.put("result_code", bundle.getInt("key_result_code", -1));
            byte[] compressed = bundle.getByteArray("value");
            if (compressed != null) {
                try (ObjectInputStream input = new ObjectInputStream(
                        new GZIPInputStream(new ByteArrayInputStream(compressed))) {
                    protected Class<?> resolveClass(ObjectStreamClass descriptor)
                            throws IOException, ClassNotFoundException {
                        try {
                            return Class.forName(descriptor.getName(), false, vendor);
                        } catch (ClassNotFoundException missing) {
                            return super.resolveClass(descriptor);
                        }
                    }
                }) {
                    result.put("points", jsonValue(input.readObject(), 0));
                }
            }
        } catch (Exception error) {
            try { result.put("error", error.toString()); } catch (Exception ignored) { }
        }
        return result;
    }

    private void sample() {
        try {
            Class<?> enums = vendor.loadClass("com.pvr.tobservice.enums.PBS_SystemInfoEnum");
            Method info = api.getClass().getMethod("pbsStateGetDeviceInfo", enums, int.class);
            info.setAccessible(true);
            String pose = String.valueOf(info.invoke(api,
                enums.getField("HMD_POSITION_AND_ORIENTATION").get(null), 0));
            String latestMap = String.valueOf(info.invoke(api,
                enums.getField("LARGESPACE_MAP_INFO").get(null), 0));
            if (samples % 20 == 0 || !latestMap.equals(map)) boundary = readBoundary();
            map = latestMap;
            JSONObject data = new JSONObject();
            data.put("run", runId);
            data.put("pose", new JSONObject(pose));
            data.put("map", new JSONObject(map));
            data.put("boundary", boundary);
            data.put("elapsed_ms", SystemClock.elapsedRealtime());
            // Room outlines can exceed Android's per-entry log size.
            String encoded = android.util.Base64.encodeToString(
                data.toString().getBytes("UTF-8"), android.util.Base64.NO_WRAP);
            int parts = (encoded.length() + 2999) / 3000;
            for (int part = 0; part < parts; part++) {
                String chunk = encoded.substring(part * 3000,
                    Math.min(encoded.length(), (part + 1) * 3000));
                Log.i("IMMENSIVA_PROBE", "PACKET " + runId + " " + samples
                    + " " + part + " " + parts + " " + chunk);
            }
        } catch (Exception error) {
            Log.e("IMMENSIVA_PROBE", "Read diagnostic failed", error);
        }
        if (++samples < 3600) handler.postDelayed(this::sample, 500);
        else stopSelf();
    }

    public void onCreate() {
        super.onCreate();
        NotificationManager notifications = getSystemService(NotificationManager.class);
        notifications.createNotificationChannel(new NotificationChannel(
            "probe", "IMMENSIVA position feed", NotificationManager.IMPORTANCE_LOW));
        startForeground(1, new Notification.Builder(this, "probe")
            .setContentTitle("IMMENSIVA position monitor")
            .setSmallIcon(android.R.drawable.ic_menu_info_details).build());
    }
    public int onStartCommand(Intent command, int flags, int startId) {
        runId = command == null ? "" : command.getStringExtra("run");
        if (bound) return START_NOT_STICKY;
        Intent intent = new Intent("com.pvr.tobservice.remoteservice");
        intent.setPackage("com.pvr.tobservice");
        bound = bindService(intent, connection, BIND_AUTO_CREATE);
        Log.i("IMMENSIVA_PROBE", "Bind requested=" + bound);
        handler.postDelayed(this::stopSelf, 1800000);
        return START_NOT_STICKY;
    }
    public IBinder onBind(Intent intent) { return null; }
    public void onDestroy() {
        handler.removeCallbacksAndMessages(null);
        if (bound) unbindService(connection);
        super.onDestroy();
    }
}
