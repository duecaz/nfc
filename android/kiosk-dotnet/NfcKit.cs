using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace LaNubeKiosk;

/// <summary>
/// Lectura NFC del panel (chip I2C via droidlogic.jar real, cargado en runtime
/// con DexClassLoader por NfcBridge.java). Ver android/NFC-Droidlogic.md.
/// </summary>
internal static class NfcKit
{
    private const string Tag        = "NfcKit";
    private const int    RegAddr    = 0x21;
    private const int    PollMs     = 50;   // i2c_read medido en ~1.7ms -> pollear rapido es gratis
    private const int    RearmPolls = 4;    // ~200ms sin tarjeta para re-armar el disparo
    private const int    RetryPolls = 40;   // ~2s entre reintentos de carga
    private const int    HbPolls    = 50;   // heartbeat de diagnostico (~2.5s)

    public static bool UseV2Chipset = false;
    public static int  I2cAddr      = 0xA6;

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool   _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static volatile bool   _ready;
    private static          Context?        _appCtx;

    private static IntPtr _cls          = IntPtr.Zero;  // referencia GLOBAL (valida entre hilos)
    private static IntPtr _loadMethod   = IntPtr.Zero;
    private static IntPtr _readMethod   = IntPtr.Zero;
    private static IntPtr _statusMethod = IntPtr.Zero;
    private static IntPtr _readUsMethod = IntPtr.Zero;

    public static void Init(Context ctx)
    {
        _appCtx = ctx.ApplicationContext ?? ctx;

        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
        }
        catch { /* Android S+: restringido, 0xA6 es el default correcto */ }

        try
        {
            // FindClass devuelve una referencia LOCAL: la promovemos a GLOBAL para
            // poder usarla con seguridad desde el hilo de polling.
            IntPtr local = JNIEnv.FindClass("uno/lanube/kiosk/NfcBridge");
            _cls = JNIEnv.NewGlobalRef(local);
            JNIEnv.DeleteLocalRef(local);

            _loadMethod   = JNIEnv.GetStaticMethodID(_cls, "load",        "(Landroid/content/Context;I)V");
            _readMethod   = JNIEnv.GetStaticMethodID(_cls, "readUid",     "(III)Ljava/lang/String;");
            _statusMethod = JNIEnv.GetStaticMethodID(_cls, "getStatus",   "()Ljava/lang/String;");
            _readUsMethod = JNIEnv.GetStaticMethodID(_cls, "getLastReadUs", "()J");

            TryLoad();
        }
        catch (Exception ex)
        {
            _ready = false;
            Log.Warn(Tag, $"NfcBridge init error: {ex.Message}");
        }
    }

    /// <summary>Carga droidlogic.jar e inicializa el bus. Devuelve true si quedo listo.</summary>
    private static bool TryLoad()
    {
        if (_cls == IntPtr.Zero || _loadMethod == IntPtr.Zero || _appCtx == null) return false;
        try
        {
            JNIEnv.CallStaticVoidMethod(_cls, _loadMethod, new JValue(_appCtx), new JValue(InitBus));
            string status = ReadStatus();
            _ready = status.StartsWith("OK");
            Log.Info(Tag, $"NfcBridge {status}  initBus={InitBus} readBus={ReadBus} addr=0x{I2cAddr:X2}");
            return _ready;
        }
        catch (Exception ex)
        {
            _ready = false;
            Log.Warn(Tag, $"NfcBridge load error: {ex.Message}");
            return false;
        }
    }

    private static string ReadStatus()
    {
        if (_statusMethod == IntPtr.Zero) return "";
        IntPtr sp = JNIEnv.CallStaticObjectMethod(_cls, _statusMethod);
        return sp == IntPtr.Zero ? "" : (JNIEnv.GetString(sp, JniHandleOwnership.TransferLocalRef) ?? "");
    }

    private static long LastReadUs()
    {
        if (_readUsMethod == IntPtr.Zero) return 0;
        return JNIEnv.CallStaticLongMethod(_cls, _readUsMethod);
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running) return;
        _running = true;
        _thread  = new Thread(ReadLoop) { IsBackground = true, Name = "NfcKit-Poll" };
        _thread.Start();
    }

    public static void StopReadJob() => _running = false;

    private static void ReadLoop()
    {
        string lastSent        = "";
        int    absent          = 0;
        int    reloadCountdown = 0;
        int    hb              = 0;

        while (_running)
        {
            // Si droidlogic no cargo (panel lento), reintentar periodicamente.
            if (!_ready)
            {
                if (--reloadCountdown <= 0) { TryLoad(); reloadCountdown = RetryPolls; }
                Thread.Sleep(PollMs);
                continue;
            }

            var uid = ReadCard();
            if (string.IsNullOrEmpty(uid))
            {
                if (++absent >= RearmPolls) lastSent = "";  // re-armar al retirar la tarjeta
            }
            else
            {
                absent = 0;
                if (uid != lastSent)                         // un solo disparo por presentacion
                {
                    lastSent = uid;
                    Log.Debug(Tag, $"tarjeta -> {uid}  (i2c_read={LastReadUs()}us)");
                    _onCard?.Invoke(uid);
                }
            }

            if (++hb % HbPolls == 0)
                Log.Debug(Tag, $"heartbeat  i2c_read={LastReadUs()}us  poll={PollMs}ms");

            Thread.Sleep(PollMs);
        }
    }

    private static string ReadCard()
    {
        if (!_ready) return "";
        try
        {
            IntPtr jstr = JNIEnv.CallStaticObjectMethod(_cls, _readMethod,
                new JValue(ReadBus), new JValue(I2cAddr), new JValue(RegAddr));
            if (jstr == IntPtr.Zero) return "";
            return JNIEnv.GetString(jstr, JniHandleOwnership.TransferLocalRef) ?? "";
        }
        catch (Exception ex)
        {
            Log.Error(Tag, $"readUid: {ex.Message}");
            return "";
        }
    }
}
