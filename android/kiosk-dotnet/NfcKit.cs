using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace LaNubeKiosk;

internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;  // REGADDR_CARD_READ
    private const int    PollMs  = 500;

    public static bool UseV2Chipset = false;
    public static int  I2cAddr     = 0xA6;  // panel: dazzle_nfc_i2c_addr=6 -> 0xA6

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;

    private static IntPtr _mgrRef  = IntPtr.Zero;
    private static IntPtr _initMid = IntPtr.Zero;
    private static IntPtr _readMid = IntPtr.Zero;

    public static void Init(Context ctx)
    {
        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
            Log.Info(Tag, $"dazzle_nfc_i2c_addr={s}  i2c_addr=0x{I2cAddr:X2}");
        }
        catch
        {
            // Android S+: clave restringida. I2cAddr=0xA6 ya es el default correcto.
            Log.Info(Tag, $"Settings restringido -> i2c_addr=0x{I2cAddr:X2} (hardcoded)");
        }

        try
        {
            var cls = JNIEnv.FindClass("com/droidlogic/app/tv/TvControlManager");

            var getInstId = JNIEnv.GetStaticMethodID(cls,
                "getInstance", "()Lcom/droidlogic/app/tv/TvControlManager;");
            var localMgr = JNIEnv.CallStaticObjectMethod(cls, getInstId);
            _mgrRef  = JNIEnv.NewGlobalRef(localMgr);
            _initMid = JNIEnv.GetMethodID(cls, "i2c_init", "(I)V");
            _readMid = JNIEnv.GetMethodID(cls, "i2c_read", "(IIII[I)I");
            JNIEnv.DeleteLocalRef(localMgr);
            JNIEnv.DeleteLocalRef(cls);

            JNIEnv.CallVoidMethod(_mgrRef, _initMid, new JValue[] { new JValue(InitBus) });
            Log.Info(Tag, $"TvControlManager JNI OK  initBus={InitBus} readBus={ReadBus} addr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            _mgrRef = IntPtr.Zero;
            Log.Warn(Tag, $"TvControlManager no disponible: {ex.Message}");
        }
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _mgrRef == IntPtr.Zero) return;
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
            if (++n % 20 == 0) Log.Debug(Tag, $"heartbeat #{n}  readBus={ReadBus}");
            if (!string.IsNullOrEmpty(uid)) _onCard?.Invoke(uid);
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
                if (ret != 0) return "";

                JNIEnv.CopyArray(jBuf, tmp);
                var uid = string.Concat(tmp.Take(4).Select(b => (b & 0xFF).ToString("X2")));
                return uid == "00000000" ? "" : uid;
            }
            finally { JNIEnv.DeleteLocalRef(jBuf); }
        }
        catch (Exception ex)
        {
            Log.Error(Tag, $"ReadCard: {ex.Message}");
            return "";
        }
    }
}
