package com.demo.nfclogin;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.provider.Settings;
import android.util.DisplayMetrics;

import java.lang.reflect.Method;

/**
 * Activity "trampolín": abre MainActivity en MODO VENTANA (freeform).
 *
 * Android 13 bloquea por reflexión el método @hide setLaunchWindowingMode
 * (restricción non-SDK). Primero levantamos esa restricción con el truco
 * VMRuntime.setHiddenApiExemptions (sin root), y luego sí lo invocamos.
 * Pasa info de diagnóstico a MainActivity (extra "dbg").
 */
public class LauncherActivity extends Activity {

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        DisplayMetrics dm = getResources().getDisplayMetrics();
        int w = 1100, h = 1750;
        int left = Math.max(0, (dm.widthPixels  - w) / 2);
        int top  = Math.max(0, (dm.heightPixels - h) / 2);
        Rect bounds = new Rect(left, top, left + w, top + h);

        int freeform = -1;
        try {
            freeform = Settings.Global.getInt(getContentResolver(), "enable_freeform_support", -1);
        } catch (Throwable ignore) {}

        String exempt = unsealHiddenApi();

        ActivityOptions opts = ActivityOptions.makeBasic();
        String refl;
        try {
            Method m = ActivityOptions.class.getDeclaredMethod("setLaunchWindowingMode", int.class);
            m.setAccessible(true);
            m.invoke(opts, 5); // WINDOWING_MODE_FREEFORM
            refl = "setWM:OK";
        } catch (Throwable t) {
            refl = "setWM:FAIL(" + t.getClass().getSimpleName() + ")";
        }
        opts.setLaunchBounds(bounds);

        String dbg = "freeform=" + freeform + " | " + exempt + " | " + refl
                   + " | bounds=" + bounds.toShortString();

        Intent i = new Intent(this, MainActivity.class);
        i.putExtra("dbg", dbg);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
        startActivity(i, opts.toBundle());
        finish();
    }

    /** Levanta la restricción non-SDK (hidden API) por meta-reflexión, sin root. */
    private String unsealHiddenApi() {
        if (Build.VERSION.SDK_INT < 28) return "exempt:NA";
        try {
            Method forName = Class.class.getDeclaredMethod("forName", String.class);
            Method getDeclaredMethod = Class.class.getDeclaredMethod(
                    "getDeclaredMethod", String.class, Class[].class);

            Class<?> vmRuntimeClass = (Class<?>) forName.invoke(null, "dalvik.system.VMRuntime");
            Method getRuntime = (Method) getDeclaredMethod.invoke(
                    vmRuntimeClass, "getRuntime", null);
            Method setExemptions = (Method) getDeclaredMethod.invoke(
                    vmRuntimeClass, "setHiddenApiExemptions", new Class[]{String[].class});

            Object vmRuntime = getRuntime.invoke(null);
            setExemptions.invoke(vmRuntime, new Object[]{ new String[]{"L"} });
            return "exempt:OK";
        } catch (Throwable t) {
            return "exempt:FAIL(" + t.getClass().getSimpleName() + ")";
        }
    }
}
