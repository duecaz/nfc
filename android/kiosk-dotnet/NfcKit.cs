using Android.Content;
using Android.Provider;
using Android.Runtime;
using Android.Util;

namespace LaNubeKiosk;

internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;
    private const int    PollMs  = 500;

    public static bool UseV2Chipset = false;
    public static int  I2cAddr     = 0xA6;  // panel: dazzle_nfc_i2c_addr=6 -> 0xA6

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static          AndroidJavaClass? _bridge;

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
            _bridge = new AndroidJavaClass("uno.lanube.kiosk.NfcBridge");
            _bridge.CallStatic("i2cInit", InitBus);
            Log.Info(Tag, $"NfcBridge OK  initBus={InitBus} readBus={ReadBus} addr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            _bridge = null;
            Log.Warn(Tag, $"NfcBridge no disponible: {ex.Message}");
        }
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _bridge == null) return;
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
            if (++n % 20 == 0) Log.Debug(Tag, $"heartbeat #{n}");
            if (!string.IsNullOrEmpty(uid)) _onCard?.Invoke(uid);
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
            Log.Error(Tag, $"readUid: {ex.Message}");
            return "";
        }
    }
}
