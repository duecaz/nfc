using Android.App;
using Android.Content;
using Android.Content.PM;
using Android.Nfc;
using Android.OS;
using Android.Views;
using Android.Webkit;

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
    private IValueCallback? filePathCallback;

    private const string KioskUrl = "https://lanube.uno";
    private const string LogTag = "LaNubeKiosk";
    private const int FileChooserCode = 1001;

    protected override void OnCreate(Bundle? savedInstanceState)
    {
        base.OnCreate(savedInstanceState);
        Window!.AddFlags(WindowManagerFlags.KeepScreenOn);

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
        webView.SetWebViewClient(new KioskWebViewClient(this));
        webView.SetWebChromeClient(new KioskWebChromeClient(this));
        webView.LoadUrl(KioskUrl);

        nfcAdapter = NfcAdapter.GetDefaultAdapter(this);
        Android.Util.Log.Debug(LogTag, $"Iniciado. NFC: {(nfcAdapter != null ? "OK" : "NO")}");
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
            (int)SystemUiFlags.ImmersiveSticky |
            (int)SystemUiFlags.LayoutStable |
            (int)SystemUiFlags.LayoutHideNavigation |
            (int)SystemUiFlags.LayoutFullscreen);
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
            if (tagObj is not Android.Nfc.Tag tag) return;
            var id = tag.GetId();
            if (id == null || id.Length == 0) return;
            var raw = BitConverter.ToString(id).Replace("-", "");
            Array.Reverse(id);
            var sb = new System.Text.StringBuilder();
            foreach (var b in id)
                sb.Append(((b & 0x0F) << 4 | (b >> 4)).ToString("X2"));
            var uid = sb.ToString();
            Android.Util.Log.Debug(LogTag, $"NFC RAW={raw} UID={uid}");
            webView.EvaluateJavascript($"if(typeof authenticate==='function')authenticate('{uid}')", null);
        }
        catch (Exception ex)
        {
            Android.Util.Log.Error(LogTag, $"NFC error: {ex.Message}");
        }
    }

    // Resultado del selector de archivos
    protected override void OnActivityResult(int requestCode, Result resultCode, Intent? data)
    {
        base.OnActivityResult(requestCode, resultCode, data);
        if (requestCode != FileChooserCode)
        {
            filePathCallback?.OnReceiveValue(null);
            filePathCallback = null;
            return;
        }
        Android.Net.Uri[]? results = null;
        if (resultCode == Result.Ok && data?.Data != null)
            results = new[] { data.Data };
        filePathCallback?.OnReceiveValue(results);
        filePathCallback = null;
    }

    public override void OnBackPressed()
    {
        if (webView.CanGoBack()) webView.GoBack();
    }

    // Recarga si hay error de red
    private class KioskWebViewClient : WebViewClient
    {
        private readonly MainActivity _host;
        public KioskWebViewClient(MainActivity host) => _host = host;

        public override void OnReceivedError(WebView? view, IWebResourceRequest? request, WebResourceError? error)
        {
            if (request?.IsForMainFrame != true) return;
            Android.Util.Log.Warn(LogTag, $"Error red: {error?.Description}");
            view?.PostDelayed(() => view.LoadUrl(KioskUrl), 5000);
        }
    }

    // Selector de archivos para subidas en Nextcloud
    private class KioskWebChromeClient : WebChromeClient
    {
        private readonly MainActivity _host;
        public KioskWebChromeClient(MainActivity host) => _host = host;

        public override bool OnShowFileChooser(
            WebView? webView,
            IValueCallback? filePathCallback,
            FileChooserParams? fileChooserParams)
        {
            // Cancelar callback anterior si quedó pendiente
            _host.filePathCallback?.OnReceiveValue(null);
            _host.filePathCallback = filePathCallback;
            try
            {
                var intent = fileChooserParams?.CreateIntent()
                    ?? new Intent(Intent.ActionOpenDocument).SetType("*/*");
                _host.StartActivityForResult(
                    Intent.CreateChooser(intent, "Seleccionar archivo"),
                    FileChooserCode);
            }
            catch (Exception ex)
            {
                Android.Util.Log.Error(LogTag, $"FileChooser error: {ex.Message}");
                _host.filePathCallback?.OnReceiveValue(null);
                _host.filePathCallback = null;
            }
            return true;
        }
    }
}
