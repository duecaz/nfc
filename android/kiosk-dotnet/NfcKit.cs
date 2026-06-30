using Android.Content;
using Android.Provider;
using Android.Util;
using Com.Droidlogic.App.TV;   // namespace generado por binding de libs\classes.jar (TV en mayusculas)

namespace LaNubeKiosk;

/// <summary>
/// Lector NFC I2C para paneles Amlogic/Droidlogic.
/// Usa TvControlManager del JAR del programador (classes.jar).
/// La implementacion real se carga desde /system/framework/droidlogic.jar del dispositivo.
///
/// API exacta (javap):
///   public static TvControlManager getInstance()    ->  TvControlManager.GetInstance()
///   public void  i2c_init(int bus)                  ->  I2cInit(int)
///   public int   i2c_read(int,int,int,int,int[])    ->  I2cRead(int,int,int,int,int[])
/// </summary>
internal static class NfcKit
{
    private const string Tag     = "NfcKit";
    private const int    RegAddr = 0x21;   // REGADDR_CARD_READ
    private const int    PollMs  = 500;

    // Chipset normal: i2c_init(bus=6), i2c_read(bus=4)  - patron del NfcKit.kt original
    // RK3576v2:       ambos buses = 7
    public static bool UseV2Chipset = false;

    // Direccion I2C: 0xA2 por defecto, sobreescrito desde Settings del sistema en Init()
    public static int I2cAddr = 0xA2;

    private static int InitBus => UseV2Chipset ? 7 : 6;
    private static int ReadBus => UseV2Chipset ? 7 : 4;

    private static volatile bool            _running;
    private static          Thread?         _thread;
    private static          Action<string>? _onCard;
    private static          TvControlManager? _mgr;

    public static void Init(Context ctx)
    {
        try
        {
            int s = Settings.Global.GetInt(ctx.ContentResolver, "dazzle_nfc_i2c_addr", 6);
            I2cAddr = s switch { 6 => 0xA6, 8 => 0xA8, _ => 0xA2 };
            Log.Info(Tag, $"dazzle_nfc_i2c_addr={s}  i2c_addr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            Log.Warn(Tag, $"No se pudo leer dazzle_nfc_i2c_addr: {ex.Message}");
        }

        try
        {
            _mgr = TvControlManager.GetInstance();
            _mgr?.I2cInit(InitBus);
            Log.Info(Tag, $"TvControlManager OK - initBus={InitBus} readBus={ReadBus} addr=0x{I2cAddr:X2}");
        }
        catch (Exception ex)
        {
            Log.Warn(Tag, $"TvControlManager no disponible: {ex.Message}");
            _mgr = null;
        }
    }

    public static void Register(Action<string> cb) => _onCard = cb;
    public static void Unregister()                 => _onCard = null;

    public static void StartReadJob()
    {
        if (_running || _mgr == null) return;
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
        if (_mgr == null) return "";
        try
        {
            var buf = new int[6];
            int ret  = _mgr.I2cRead(ReadBus, I2cAddr, RegAddr, 5, buf);
            if (ret != 0) return "";

            // 4 bytes -> 8 chars hex mayuscula con padding, ej: "D779CD0A"
            var uid = string.Concat(buf.Take(4).Select(b => (b & 0xFF).ToString("X2")));
            return uid == "00000000" ? "" : uid;
        }
        catch (Exception ex)
        {
            Log.Error(Tag, $"ReadCard: {ex.Message}");
            return "";
        }
    }
}
