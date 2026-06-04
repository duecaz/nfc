package com.demo.nfclogin;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Bundle;
import android.provider.Settings;
import android.util.DisplayMetrics;

/**
 * Activity "trampolín": abre MainActivity en MODO VENTANA (freeform).
 * Recolecta info de diagnóstico y se la pasa a MainActivity (extra "dbg")
 * para mostrarla en pantalla y entender por qué abre full o ventana.
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

        ActivityOptions opts = ActivityOptions.makeBasic();
        String refl;
        try {
            java.lang.reflect.Method m =
                ActivityOptions.class.getMethod("setLaunchWindowingMode", int.class);
            m.invoke(opts, 5); // WINDOWING_MODE_FREEFORM
            refl = "setWM:OK";
        } catch (Throwable t) {
            refl = "setWM:FAIL(" + t.getClass().getSimpleName() + ")";
        }
        opts.setLaunchBounds(bounds);

        String dbg = "freeform=" + freeform + " | " + refl
                   + " | bounds=" + bounds.toShortString();

        Intent i = new Intent(this, MainActivity.class);
        i.putExtra("dbg", dbg);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
        startActivity(i, opts.toBundle());
        finish();
    }
}
