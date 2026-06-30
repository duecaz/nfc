using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace NfcTest;

internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;
    private const int    PollMs  = 200;

    public static bool   UseV2Chipset = false;
    public static int    I2cAddr      = 0xA6;
    public static int    ReadCount    = 0;
    public static string LastUid      = "";

    public static readonly List<string> Steps = new();

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static          bool            _ready;

    private static IntPtr _cls        = IntPtr.Zero;
    private static IntPtr _readMethod = IntPtr.Zero;

    public static bool IsReady => _ready;

    private static void Step(string msg)
    {
        Log.Debug(Tag, msg);
        lock (Steps) { Steps.Add(msg); }
    }

    public static void Init(Context ctx)
    {
        Steps.Clear();
        Step("[1] Init arranca");

        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
            Step($"[2] i2cAddr=0x{I2cAddr:X2} (settings={s})");
        }
        catch
        {
            Step($"[2] Settings restringido -> i2cAddr=0x{I2cAddr:X2} (hardcoded)");
        }

        try
        {
            Step("[3] FindClass NfcBridge...");
            _cls = JNIEnv.FindClass("uno/lanube/nfctest/NfcBridge");
            Step("[3] OK");

            IntPtr loadM   = JNIEnv.GetStaticMethodID(_cls, "load", "(Landroid/content/Context;I)V");
            IntPtr statusM = JNIEnv.GetStaticMethodID(_cls, "getStatus", "()Ljava/lang/String;");
            _readMethod    = JNIEnv.GetStaticMethodID(_cls, "readUid", "(III)Ljava/lang/String;");

            Step($"[4] load(ctx, initBus={InitBus})...");
            JNIEnv.CallStaticVoidMethod(_cls, loadM, new JValue(ctx), new JValue(InitBus));

            IntPtr sp = JNIEnv.CallStaticObjectMethod(_cls, statusM);
            string status = sp == IntPtr.Zero
                ? ""
                : (JNIEnv.GetString(sp, JniHandleOwnership.TransferLocalRef) ?? "");
            Step($"[5] {status}");

            _ready = status.StartsWith("OK");
            Step(_ready
                ? $"[6] LISTO  readBus={ReadBus}  addr=0x{I2cAddr:X2}"
                : "[6] NO LISTO - droidlogic no cargado");
        }
        catch (Exception ex)
        {
            _ready = false;
            Step($"[ERR] {ex.GetType().Name}: {ex.Message}");
        }
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || !_ready) { Step($"[POLL] skip: ready={_ready}"); return; }
        Step("[POLL] hilo iniciado");
        _running = true;
        _thread  = new Thread(ReadLoop) { IsBackground = true, Name = "NfcKit-Poll" };
        _thread.Start();
    }

    public static void StopReadJob() => _running = false;

    private static void ReadLoop()
    {
        while (_running)
        {
            var uid = ReadCard();
            if (!string.IsNullOrEmpty(uid))
            {
                LastUid = uid;
                ReadCount++;
                _onCard?.Invoke(uid);
            }
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
            Step($"[ERR] readUid: {ex.Message}");
            return "";
        }
    }
}
