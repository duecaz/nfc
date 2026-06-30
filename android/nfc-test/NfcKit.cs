using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace NfcTest;

internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;
    private const int    PollMs  = 500;

    public static bool   UseV2Chipset = false;
    public static int    I2cAddr      = 0xA6;  // panel: dazzle_nfc_i2c_addr=6 -> 0xA6
    public static string LastError    = "(ninguno)";
    public static int    ReadCount    = 0;
    public static int    LastRet      = -99;
    public static string LastBuf      = "";
    public static string LastUid      = "";

    public static readonly List<string> Steps = new();

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;

    private static IntPtr _mgrRef  = IntPtr.Zero;
    private static IntPtr _initMid = IntPtr.Zero;
    private static IntPtr _readMid = IntPtr.Zero;

    private static void Step(string msg)
    {
        Log.Debug(Tag, msg);
        lock (Steps) { Steps.Add(msg); }
    }

    public static void Init(Context ctx)
    {
        Steps.Clear();
        Step("[1] Init() arranca");

        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
            Step($"[2] dazzle_nfc_i2c_addr={s}  I2cAddr=0x{I2cAddr:X2}");
        }
        catch
        {
            // Android S+: clave restringida. I2cAddr=0xA6 ya es el default correcto.
            Step($"[2] Settings restringido (Android S+) -> I2cAddr=0x{I2cAddr:X2} (hardcoded)");
        }

        try
        {
            Step("[3] FindClass TvControlManager...");
            var cls = JNIEnv.FindClass("com/droidlogic/app/tv/TvControlManager");
            Step($"[3] FindClass OK  cls=0x{cls:X}");

            Step("[4] GetStaticMethodID getInstance...");
            var getInstId = JNIEnv.GetStaticMethodID(cls,
                "getInstance", "()Lcom/droidlogic/app/tv/TvControlManager;");
            Step($"[4] OK  id=0x{getInstId:X}");

            Step("[5] getInstance()...");
            var localMgr = JNIEnv.CallStaticObjectMethod(cls, getInstId);
            Step($"[5] OK  obj=0x{localMgr:X}");

            _mgrRef = JNIEnv.NewGlobalRef(localMgr);
            JNIEnv.DeleteLocalRef(localMgr);

            _initMid = JNIEnv.GetMethodID(cls, "i2c_init", "(I)V");
            Step($"[6] i2c_init methodID OK");

            _readMid = JNIEnv.GetMethodID(cls, "i2c_read", "(IIII[I)I");
            Step($"[7] i2c_read methodID OK");

            JNIEnv.DeleteLocalRef(cls);

            Step($"[8] i2c_init(bus={InitBus})...");
            JNIEnv.CallVoidMethod(_mgrRef, _initMid, new JValue[] { new JValue(InitBus) });
            Step($"[9] LISTO  readBus={ReadBus}  i2cAddr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            LastError = ex.Message;
            _mgrRef   = IntPtr.Zero;
            Step($"[ERR] {ex.GetType().Name}: {ex.Message}");
        }
    }

    public static bool IsReady => _mgrRef != IntPtr.Zero;

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _mgrRef == IntPtr.Zero)
        {
            Step($"[POLL] skip: running={_running} ready={IsReady}");
            return;
        }
        Step("[POLL] hilo iniciado");
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
            n++;
            if (n % 10 == 0) Log.Debug(Tag, $"heartbeat #{n} ret={LastRet} buf={LastBuf}");
            if (!string.IsNullOrEmpty(uid))
            {
                LastUid = uid;
                _onCard?.Invoke(uid);
            }
            Thread.Sleep(PollMs);
        }
    }

    private static string ReadCard()
    {
        if (_mgrRef == IntPtr.Zero || _readMid == IntPtr.Zero) return "";
        try
        {
            int[] tmp  = new int[6];
            var   jBuf = JNIEnv.NewArray(tmp);
            try
            {
                int ret = JNIEnv.CallIntMethod(_mgrRef, _readMid, new JValue[]
                {
                    new JValue(ReadBus), new JValue(I2cAddr),
                    new JValue(RegAddr), new JValue(5),
                    new JValue(jBuf)
                });
                LastRet = ret;
                JNIEnv.CopyArray(jBuf, tmp);
                LastBuf = string.Join(",", tmp.Take(5).Select(b => $"{b:X2}"));

                if (ret != 0) return "";

                var uid = string.Concat(tmp.Take(4).Select(b => (b & 0xFF).ToString("X2")));
                ReadCount++;
                return uid == "00000000" ? "" : uid;
            }
            finally { JNIEnv.DeleteLocalRef(jBuf); }
        }
        catch (Exception ex)
        {
            LastRet = -1;
            LastBuf = $"EX:{ex.Message}";
            return "";
        }
    }
}
