using Android.App;
using Android.OS;
using Android.Widget;

namespace NfcTest;

[Activity(Label = "NFC Test", MainLauncher = true,
    Theme = "@android:style/Theme.Black.NoTitleBar.Fullscreen")]
public class MainActivity : Activity
{
    private TextView _tvSteps = null!;
    private TextView _tvPoll  = null!;
    private TextView _tvUid   = null!;
    private System.Timers.Timer? _timer;

    protected override void OnCreate(Android.OS.Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        SetContentView(Resource.Layout.activity_main);
        _tvSteps = FindViewById<TextView>(Resource.Id.tvSteps)!;
        _tvPoll  = FindViewById<TextView>(Resource.Id.tvPoll)!;
        _tvUid   = FindViewById<TextView>(Resource.Id.tvUid)!;

        NfcKit.Init(this);

        // Mostrar pasos de init inmediatamente
        UpdateSteps();
    }

    protected override void OnResume()
    {
        base.OnResume();
        NfcKit.Register(uid => RunOnUiThread(() => _tvUid.Text = uid));
        NfcKit.StartReadJob();

        // Actualizar pantalla cada 500ms con estado del poll
        _timer = new System.Timers.Timer(500);
        _timer.Elapsed += (_, _) => RunOnUiThread(UpdatePoll);
        _timer.Start();
    }

    protected override void OnPause()
    {
        base.OnPause();
        _timer?.Stop();
        _timer?.Dispose();
        _timer = null;
        NfcKit.StopReadJob();
        NfcKit.Unregister();
    }

    private void UpdateSteps()
    {
        string text;
        lock (NfcKit.Steps) { text = string.Join("\n", NfcKit.Steps); }
        _tvSteps.Text = text;
    }

    private void UpdatePoll()
    {
        _tvPoll.Text =
            $"reads={NfcKit.ReadCount}  ret={NfcKit.LastRet}\n" +
            $"buf: {NfcKit.LastBuf}\n" +
            $"uid: {(string.IsNullOrEmpty(NfcKit.LastUid) ? "---" : NfcKit.LastUid)}";
    }
}
