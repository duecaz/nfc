package uno.lanube.kiosk;

import android.content.Context;
import android.util.Log;
import dalvik.system.DexClassLoader;
import java.io.File;
import java.lang.reflect.Method;

/**
 * Carga el TvControlManager REAL desde /system/framework/droidlogic.jar via
 * DexClassLoader (igual que la app de Android Studio que si lee la tarjeta).
 * Usa reflexion: NO requiere classes.jar para compilar.
 */
public class NfcBridge {
    private static final String TAG = "NfcBridge";

    private static Object tvManager;
    private static Method i2cReadMethod;
    private static String status = "sin-init";

    public static String getStatus() { return status; }

    public static void load(Context ctx, int initBus) {
        String[] jars = {
            "/system/framework/droidlogic.jar",
            "/system/framework/droidlogic-tv.jar",
            "/system/framework/droidlogic.software.core.jar",
            "/system/framework/droidlogic.tv.software.core.jar"
        };
        String cache = ctx.getCacheDir().getAbsolutePath();
        for (String path : jars) {
            if (!new File(path).exists()) continue;
            try {
                DexClassLoader loader = new DexClassLoader(
                        path, cache, null, ClassLoader.getSystemClassLoader());
                Class<?> cls = loader.loadClass("com.droidlogic.app.tv.TvControlManager");
                Method getInstance = cls.getMethod("getInstance");
                tvManager = getInstance.invoke(null);
                Method i2cInit = cls.getMethod("i2c_init", int.class);
                i2cReadMethod = cls.getMethod("i2c_read",
                        int.class, int.class, int.class, int.class, int[].class);
                i2cInit.invoke(tvManager, initBus);
                status = "OK desde " + path;
                Log.i(TAG, status);
                return;
            } catch (Throwable e) {
                status = "fallo " + path + ": " + e.getClass().getSimpleName()
                         + ": " + e.getMessage();
                Log.w(TAG, status);
            }
        }
        if (tvManager == null) status = "NO encontrado en /system/framework/";
    }

    public static String readUid(int bus, int addr, int reg) {
        if (i2cReadMethod == null || tvManager == null) return "";
        try {
            int[] temp = new int[6];
            int ret = (Integer) i2cReadMethod.invoke(tvManager, bus, addr, reg, 5, temp);
            if (ret != 0) return "";
            StringBuilder sb = new StringBuilder(8);
            for (int i = 0; i < 4; i++) {
                String h = Integer.toHexString(temp[i] & 0xFF);
                if (h.length() < 2) sb.append('0');
                sb.append(h);
            }
            String uid = sb.toString();
            return uid.equals("00000000") ? "" : uid;
        } catch (Throwable e) {
            Log.e(TAG, "readUid: " + e.getMessage());
            return "";
        }
    }
}
