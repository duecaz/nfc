package com.demo.nfclogin;

import android.app.Activity;
import android.content.Context;
import android.os.Bundle;
import android.os.Process;
import android.os.UserManager;
import android.webkit.JavascriptInterface;
import android.webkit.WebSettings;
import android.webkit.WebView;

import java.util.HashMap;
import java.util.Map;

/**
 * Login NFC para paneles RK3588 con NFC "dazzle".
 *
 * En estos paneles el lector NFC es un módulo cerrado (MCU GD32 por I2C) que
 * gestiona el servicio "dazzle": al leer la tarjeta NO expone el UID, sino que
 * CAMBIA el perfil de usuario de Android (user 0, 10, 11, ...).
 *
 * SELinux impide que una app normal lea /dev/i2c-6, así que NO leemos el chip.
 * En cambio usamos lo que el hardware sí entrega: el PERFIL activo. Cada app
 * conoce su propio usuario (Process.myUserHandle()), así que con la app
 * corriendo en cada perfil, "tarjeta -> perfil -> cuenta".
 *
 * La UI es el index.html del repo (cargado en este WebView). El puente
 * DazzleBridge le pasa el perfil para que haga auto-login.
 */
public class MainActivity extends Activity {

    // ========================================================================
    // MAPA  perfil (serial de usuario Android)  ->  nombre de cuenta
    // ------------------------------------------------------------------------
    // El serial lo ves con:   adb shell dumpsys user      (serialNo=...)
    // Si un perfil no está acá, la app te muestra su id en pantalla para que
    // lo agregues. Asociá cada tarjeta a un perfil desde los ajustes del panel.
    //
    // TODO SUPABASE: en producción, en vez de este mapa fijo, consultá Supabase
    // usando el serial del perfil como clave de la cuenta.
    // ========================================================================
    private static final Map<Long, String> USERS = new HashMap<>();
    static {
        USERS.put(0L,  "Administrador");
        USERS.put(10L, "profe1");
        // USERS.put(11L, "profe2");
        // USERS.put(12L, "profe3");
    }

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        web = new WebView(this);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);              // necesario para localStorage
        web.addJavascriptInterface(new Bridge(), "DazzleBridge");
        setContentView(web);

        // Mockup/cáscara para mostrar a dazzle (login + home estilo Drive).
        // Para volver al login por perfil real, cambiá a "index.html".
        web.loadUrl("file:///android_asset/mockup.html");
    }

    @Override
    protected void onResume() {
        super.onResume();
        // Al volver a primer plano (p.ej. tras un cambio de perfil por NFC)
        // recargamos para re-evaluar el login del perfil activo.
        if (web != null) {
            web.reload();
        }
    }

    /** Puente JS<->nativo expuesto como window.DazzleBridge en la web. */
    public class Bridge {

        private long serial() {
            UserManager um = (UserManager) getSystemService(Context.USER_SERVICE);
            return um.getSerialNumberForUser(Process.myUserHandle());
        }

        @JavascriptInterface
        public String getUserId() {
            return String.valueOf(serial());
        }

        @JavascriptInterface
        public String getUserName() {
            String name = USERS.get(serial());
            return name == null ? "" : name;
        }
    }
}
