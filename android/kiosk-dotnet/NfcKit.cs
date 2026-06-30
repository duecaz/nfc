using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace LaNubeKiosk;

/// <summary>
/// Polls the built-in I2C NFC reader found on Amlogic/Droidlogic panels
/// via TvControlManager loaded at runtime from /system/framework/droidlogic.jar.
/// Falls back silently if the jar is absent (regular Android devices).
/// </summary>
internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;
    private const int    PollMs  = 200;

    public static int I2cBus  = 4;
    public static int I2cAddr = 0xA6;

    private static volatile bool    _running;
    private static          Thread? _thread;
    private static          Action<string>? _onCard;

    // JNI global refs – kept alive so method IDs remain valid
    private static IntPtr _tvManager  = IntPtr.Zero;
    private static IntPtr _tvClass    = IntPtr.Zero;
    private static IntPtr _initMethod = IntPtr.Zero;
    private static IntPtr _readMethod = IntPtr.Zero;

    private static readonly string[] JarPaths =
    [
        "/system/framework/droidlogic.jar",
        "/system/framework/droidlogic-tv.jar",
        "/system/framework/droidlogic.software.core.jar",
        "/system/framework/droidlogic.tv.software.core.jar",
    ];

    public static void Init(Context ctx)
    {
        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
        }
        catch { /* SecurityException on some ROMs – keep default */ }

        if (_tvManager == IntPtr.Zero)
            LoadManager(ctx);

        if (_tvManager != IntPtr.Zero)
        {
            try
            {
                int busArg = I2cBus == 7 ? 7 : 6;
                JNIEnv.CallVoidMethod(_tvManager, _initMethod, new JValue(busArg));
                Log.Info(Tag, $"i2c_init({busArg}) OK  addr=0x{I2cAddr:X2}");
            }
            catch (Exception ex) { Log.Error(Tag, $"i2c_init: {ex.Message}"); }
        }
    }

    private static void LoadManager(Context ctx)
    {
        string cache = ctx.CacheDir!.AbsolutePath;

        foreach (var jar in JarPaths)
        {
            if (!File.Exists(jar)) continue;
            try
            {
                // --- Create DexClassLoader via JNI ---
                var clsDex = JNIEnv.FindClass("dalvik/system/DexClassLoader");
                var ctorId = JNIEnv.GetMethodID(clsDex, "<init>",
                    "(Ljava/lang/String;Ljava/lang/String;Ljava/lang/String;Ljava/lang/ClassLoader;)V");

                var clsLoader = JNIEnv.FindClass("java/lang/ClassLoader");
                var getSysId  = JNIEnv.GetStaticMethodID(clsLoader,
                    "getSystemClassLoader", "()Ljava/lang/ClassLoader;");
                var sysLoader = JNIEnv.CallStaticObjectMethod(clsLoader, getSysId);

                var loader = JNIEnv.NewObject(clsDex, ctorId,
                    new JValue(new Java.Lang.String(jar)),
                    new JValue(new Java.Lang.String(cache)),
                    new JValue(IntPtr.Zero),
                    new JValue(sysLoader));

                // --- loader.loadClass("com.droidlogic.app.tv.TvControlManager") ---
                var loadClassId = JNIEnv.GetMethodID(clsDex, "loadClass",
                    "(Ljava/lang/String;)Ljava/lang/Class;");
                var tvCls = JNIEnv.CallObjectMethod(loader, loadClassId,
                    new JValue(new Java.Lang.String("com.droidlogic.app.tv.TvControlManager")));

                // --- TvControlManager.getInstance() ---
                var getInstId = JNIEnv.GetStaticMethodID(tvCls, "getInstance",
                    "()Lcom/droidlogic/app/tv/TvControlManager;");
                var instance  = JNIEnv.CallStaticObjectMethod(tvCls, getInstId);

                // Keep global refs so method IDs stay valid
                _tvClass    = JNIEnv.NewGlobalRef(tvCls);
                _tvManager  = JNIEnv.NewGlobalRef(instance);
                _initMethod = JNIEnv.GetMethodID(_tvClass, "i2c_init", "(I)V");
                _readMethod = JNIEnv.GetMethodID(_tvClass, "i2c_read", "(IIII[I)I");

                JNIEnv.DeleteLocalRef(tvCls);
                JNIEnv.DeleteLocalRef(instance);
                JNIEnv.DeleteLocalRef(loader);

                Log.Info(Tag, $"TvControlManager cargado desde {jar}");
                return;
            }
            catch (Exception ex)
            {
                Log.Warn(Tag, $"Fallo {jar}: {ex.GetType().Name}: {ex.Message}");
            }
        }
        Log.Warn(Tag, "TvControlManager NO encontrado – NFC I2C no disponible");
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _tvManager == IntPtr.Zero) return;
        _running = true;
        _thread  = new Thread(ReadLoop) { IsBackground = true, Name = "NfcKit-Poll" };
        _thread.Start();
    }

    public static void StopReadJob()
    {
        _running = false;
    }

    private static void ReadLoop()
    {
        int n = 0;
        while (_running)
        {
            var uid = ReadCard();
            if (++n % 25 == 0) Log.Debug(Tag, $"heartbeat #{n} bus={I2cBus}");
            if (!string.IsNullOrEmpty(uid)) _onCard?.Invoke(uid);
            Thread.Sleep(PollMs);
        }
    }

    private static string ReadCard()
    {
        if (_tvManager == IntPtr.Zero || _readMethod == IntPtr.Zero) return "";
        try
        {
            var jArr = JNIEnv.NewArray(new int[6]);
            var ret  = JNIEnv.CallIntMethod(_tvManager, _readMethod,
                new JValue(I2cBus),
                new JValue(I2cAddr),
                new JValue(RegAddr),
                new JValue(5),
                new JValue(jArr));

            var buf = new int[6];
            JNIEnv.CopyArray(jArr, buf);
            JNIEnv.DeleteLocalRef(jArr);

            if (ret != 0) return "";
            var uid = string.Concat(buf.Take(4).Select(b => b.ToString("x2").PadLeft(2, '0')));
            return uid == "00000000" ? "" : uid;
        }
        catch (Exception ex)
        {
            Log.Error(Tag, $"ReadCard: {ex.Message}");
            return "";
        }
    }
}
