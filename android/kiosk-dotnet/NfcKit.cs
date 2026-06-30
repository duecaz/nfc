using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace LaNubeKiosk;

internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;
    private const int    PollMs  = 200;

    public static bool UseV2Chipset = false;
    public static int  I2cAddr     = 0xA6;

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static          bool            _ready;

    private static IntPtr _cls        = IntPtr.Zero;
    private static IntPtr _readMethod = IntPtr.Zero;

    public static void Init(Context ctx)
    {
        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
        }
        catch { /* Android S+: restringido, 0xA6 es el default correcto */ }

        try
        {
            _cls = JNIEnv.FindClass("uno/lanube/kiosk/NfcBridge");
            IntPtr loadM = JNIEnv.GetStaticMethodID(_cls, "load", "(Landroid/content/Context;I)V");
            _readMethod  = JNIEnv.GetStaticMethodID(_cls, "readUid", "(III)Ljava/lang/String;");
            JNIEnv.CallStaticVoidMethod(_cls, loadM, new JValue(ctx), new JValue(InitBus));

            IntPtr statusM = JNIEnv.GetStaticMethodID(_cls, "getStatus", "()Ljava/lang/String;");
            IntPtr sp = JNIEnv.CallStaticObjectMethod(_cls, statusM);
            string status = sp == IntPtr.Zero
                ? ""
                : (JNIEnv.GetString(sp, JniHandleOwnership.TransferLocalRef) ?? "");

            _ready = status.StartsWith("OK");
            Log.Info(Tag, $"NfcBridge {status}  initBus={InitBus} readBus={ReadBus} addr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            _ready = false;
            Log.Warn(Tag, $"NfcBridge no disponible: {ex.Message}");
        }
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || !_ready) return;
        _running = true;
        _thread  = new Thread(ReadLoop) { IsBackground = true, Name = "NfcKit-Poll" };
        _thread.Start();
    }

    public static void StopReadJob() => _running = false;

    private static void ReadLoop()
    {
        int n = 0;
        while (_running)
        {
            var uid = ReadCard();
            if (++n % 25 == 0) Log.Debug(Tag, $"heartbeat #{n}");
            if (!string.IsNullOrEmpty(uid)) _onCard?.Invoke(uid);
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
