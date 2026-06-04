package com.demo.nfclogin;

import android.app.Activity;
import android.app.ActivityOptions;
import android.content.Intent;
import android.graphics.Rect;
import android.os.Bundle;
import android.util.DisplayMetrics;

/**
 * Activity "trampolín": es la que tiene el ícono en el launcher.
 * Al abrirse, lanza MainActivity en MODO VENTANA (freeform) y se cierra.
 *
 * Por qué así: una app no puede declararse "ventana" en el manifest; el modo
 * lo define QUIEN la lanza, vía ActivityOptions. Si pasamos setLaunchBounds(rect)
 * y el dispositivo soporta freeform (este panel sí: enable_freeform_support=1),
 * la activity se abre flotante con ese tamaño/posición.
 */
public class LauncherActivity extends Activity {

    @Override
    protected void onCreate(Bundle b) {
        super.onCreate(b);

        // Tamaño y posición de la ventana (centrada). Ajustá a gusto.
        DisplayMetrics dm = getResources().getDisplayMetrics();
        int w = 1100, h = 1750;                         // px de la ventana
        int left = Math.max(0, (dm.widthPixels  - w) / 2);
        int top  = Math.max(0, (dm.heightPixels - h) / 2);
        Rect bounds = new Rect(left, top, left + w, top + h);

        ActivityOptions opts = ActivityOptions.makeBasic();

        // Forzar MODO VENTANA (freeform = 5). setLaunchWindowingMode es API @hide;
        // la invocamos por reflexión (es lo que hace `am start --windowingMode 5`,
        // que en este panel SÍ abre en ventana). setLaunchBounds le da tamaño/posición.
        try {
            java.lang.reflect.Method m =
                ActivityOptions.class.getMethod("setLaunchWindowingMode", int.class);
            m.invoke(opts, 5); // WINDOWING_MODE_FREEFORM
        } catch (Throwable ignore) { }
        opts.setLaunchBounds(bounds);

        Intent i = new Intent(this, MainActivity.class);
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_MULTIPLE_TASK);
        startActivity(i, opts.toBundle());
        finish();                                       // el trampolín no deja UI
    }
}
