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
    public static int    I2cAddr      = 0xA6;
    public static int    ReadCount    = 0;
    public static string LastUid      = "";

    public static readonly List<string> Steps = new();

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static          AndroidJavaClass? _bridge;

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
            Step("[3] AndroidJavaClass NfcBridge...");
            _bridge = new AndroidJavaClass("uno.lanube.nfctest.NfcBridge");
            Step("[3] OK");

            Step($"[4] i2cInit(bus={InitBus})...");
            _bridge.CallStatic("i2cInit", InitBus);
            Step($"[4] OK");

            Step($"[5] LISTO  readBus={ReadBus}  i2cAddr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            _bridge = null;
            Step($"[ERR] {ex.GetType().Name}: {ex.Message}");
        }
    }

    public static bool IsReady => _bridge != null;

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _bridge == null) { Step($"[POLL] skip: ready={IsReady}"); return; }
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
        if (_bridge == null) return "";
        try
        {
            return _bridge.CallStatic<string>("readUid", ReadBus, I2cAddr, RegAddr) ?? "";
        }
        catch (Exception ex)
        {
            Step($"[ERR] readUid: {ex.Message}");
            return "";
        }
    }
}
