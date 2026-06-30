using Android.App;
using Android.OS;
using Android.Widget;

namespace NfcTest;

[Activity(Label = "NFC Test", MainLauncher = true,
    Theme = "@android:style/Theme.Black.NoTitleBar.Fullscreen")]
public class MainActivity : Activity
{
    private TextView _tvStatus = null!;
    private TextView _tvUid    = null!;
    private TextView _tvLast   = null!;
    private readonly List<string> _history = new();

    protected override void OnCreate(Android.OS.Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        SetContentView(Resource.Layout.activity_main);

        _tvStatus = FindViewById<TextView>(Resource.Id.tvStatus)!;
        _tvUid    = FindViewById<TextView>(Resource.Id.tvUid)!;
        _tvLast   = FindViewById<TextView>(Resource.Id.tvLast)!;

        NfcKit.Init(this);

        if (NfcKit.IsReady)
            _tvStatus.Text =
                $"TvControlManager OK\n" +
                $"initBus={(NfcKit.UseV2Chipset ? 7 : 6)}  " +
                $"readBus={(NfcKit.UseV2Chipset ? 7 : 4)}  " +
                $"i2cAddr=0x{NfcKit.I2cAddr:X2}";
        else
            _tvStatus.Text = $"ERROR: {NfcKit.InitError}";
    }

    protected override void OnResume()
    {
        base.OnResume();
        NfcKit.Register(uid => RunOnUiThread(() =>
        {
            _tvUid.Text = uid;
            _history.Insert(0, uid);
            if (_history.Count > 8) _history.RemoveAt(8);
            _tvLast.Text = string.Join("\n", _history);
        }));
        NfcKit.StartReadJob();
    }

    protected override void OnPause()
    {
        base.OnPause();
        NfcKit.StopReadJob();
        NfcKit.Unregister();
    }
}
