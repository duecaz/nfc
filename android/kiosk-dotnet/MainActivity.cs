using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.Nfc;
using Android.OS;
using Android.Views;
using Android.Webkit;
using Android.Widget;

namespace LaNubeKiosk;

[Activity(
    Label = "@string/app_name",
    MainLauncher = true,
    LaunchMode = LaunchMode.SingleTop,
    ConfigurationChanges = ConfigChanges.Orientation | ConfigChanges.KeyboardHidden | ConfigChanges.ScreenSize)]
public class MainActivity : Activity
{
    private WebView webView = null!;
    private NfcAdapter? nfcAdapter;
    private const string KioskUrl = "https://lanube.uno";
    private const string Tag = "LaNubeKiosk";

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);

        webView = new WebView(this);
        SetContentView(webView);

        CookieManager.Instance?.SetAcceptCookie(true);
        CookieManager.Instance?.SetAcceptThirdPartyCookies(webView, true);

        webView.Settings!.JavaScriptEnabled = true;
        webView.Settings.DomStorageEnabled = true;
        webView.Settings.SetSupportZoom(false);
        webView.Settings.BuiltInZoomControls = false;
        webView.Settings.DisplayZoomControls = false;
        webView.Settings.UseWideViewPort = true;
        webView.Settings.LoadWithOverviewMode = true;
        webView.SetWebViewClient(new WebViewClient());
        webView.SetWebChromeClient(new WebChromeClient());
        webView.LoadUrl(KioskUrl);

        nfcAdapter = NfcAdapter.GetDefaultAdapter(this);
        Android.Util.Log.Debug(Tag, $"v7 iniciado. NFC: {(nfcAdapter != null ? "OK" : "NO")}");

        Toast.MakeText(this, "La Nube v7", ToastLength.Long)?.Show();
        HideSystemUI();
    }

    public override void OnWindowFocusChanged(bool hasFocus)
    {
        base.OnWindowFocusChanged(hasFocus);
        if (hasFocus) HideSystemUI();
    }

    private void HideSystemUI()
    {
#pragma warning disable CA1416, CS0618
        Window!.DecorView.SystemUiVisibility = (StatusBarVisibility)(
            (int)SystemUiFlags.Fullscreen |
            (int)SystemUiFlags.HideNavigation |
            (int)SystemUiFlags.ImmersiveSticky);
#pragma warning restore CA1416, CS0618
    }

    protected override void OnResume()
    {
        base.OnResume();
        if (nfcAdapter == null) return;
        var intent = new Intent(this, typeof(MainActivity));
        intent.AddFlags(ActivityFlags.SingleTop);
#pragma warning disable CA1416
        var flags = Build.VERSION.SdkInt >= BuildVersionCodes.S
            ? PendingIntentFlags.Mutable
            : (PendingIntentFlags)0;
#pragma warning restore CA1416
        var pending = PendingIntent.GetActivity(this, 0, intent, flags);
        nfcAdapter.EnableForegroundDispatch(this, pending, null, null);
    }

    protected override void OnPause()
    {
        base.OnPause();
        nfcAdapter?.DisableForegroundDispatch(this);
    }

    protected override void OnNewIntent(Intent? intent)
    {
        base.OnNewIntent(intent);
        if (intent == null) return;

        try
        {
#pragma warning disable CA1422
            var tagObj = intent.GetParcelableExtra(NfcAdapter.ExtraTag);
#pragma warning restore CA1422
            if (tagObj is not Android.Nfc.Tag tag)
            {
                Android.Util.Log.Warn(Tag, "NFC intent sin tag");
                return;
            }

            var id = tag.GetId();
            if (id == null || id.Length == 0)
            {
                Android.Util.Log.Warn(Tag, "GetId() vacio");
                return;
            }

            var raw = BitConverter.ToString(id).Replace("-", "");
            Android.Util.Log.Debug(Tag, $"RAW bytes: {raw}");

            Array.Reverse(id);
            var sb = new System.Text.StringBuilder();
            foreach (var b in id)
                sb.Append(((b & 0x0F) << 4 | (b >> 4)).ToString("X2"));
            var uid = sb.ToString();

            Android.Util.Log.Debug(Tag, $"UID calculado: {uid}");
            webView.EvaluateJavascript($"if(typeof authenticate==='function')authenticate('{uid}')", null);
        }
        catch (Exception ex)
        {
            Android.Util.Log.Error(Tag, $"Error NFC: {ex.Message}");
        }
    }

    public override void OnBackPressed()
    {
        if (webView.CanGoBack()) webView.GoBack();
    }
}
