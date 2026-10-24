package com.kgc.stub;

import android.app.Activity;
import android.graphics.Color;
import android.media.MediaPlayer;
import android.net.Uri;
import android.view.Gravity;
import android.view.KeyEvent;
import android.view.MotionEvent;
import android.view.View;
import android.view.ViewGroup;
import android.widget.FrameLayout;
import android.widget.TextView;
import android.widget.VideoView;

/**
 * Full-screen video overlay for skin intro.
 * Called from native stub.cpp via JNI after loading this class from an embedded DEX.
 *
 * Flow:
 *   1. Native hook on CardInfoPanel calls play(activity, url)
 *   2. Activity.runOnUiThread creates a full-screen black FrameLayout + VideoView overlay
 *   3. Video plays; on completion/error/tap/back -> overlay removed -> nativeOnVideoComplete()
 *   4. Native callback sets flag to dispatch original skin show on Unity main thread
 */
public class VideoOverlay {
    private static FrameLayout sContainer;
    private static VideoView sVideoView;
    private static volatile boolean sCleanedUp = false;

    /**
     * Launch the video overlay on the Android UI thread.
     */
    public static void play(final Activity activity, final String url) {
        if (activity == null || activity.isFinishing()) {
            cleanup();
            return;
        }

        activity.runOnUiThread(new Runnable() {
            @Override
            public void run() {
                try {
                    sCleanedUp = false;

                    // Root container: full-screen solid black
                    sContainer = new FrameLayout(activity);
                    sContainer.setBackgroundColor(Color.BLACK);
                    sContainer.setClickable(true);
                    sContainer.setFocusable(true);
                    sContainer.setFocusableInTouchMode(true);

                    // VideoView centered in the container
                    sVideoView = new VideoView(activity);
                    FrameLayout.LayoutParams vpLp = new FrameLayout.LayoutParams(
                            ViewGroup.LayoutParams.MATCH_PARENT,
                            ViewGroup.LayoutParams.MATCH_PARENT);
                    vpLp.gravity = Gravity.CENTER;
                    sContainer.addView(sVideoView, vpLp);

                    // "Tap to skip" hint text (bottom-center, translucent white)
                    TextView skipHint = new TextView(activity);
                    skipHint.setText("Tap to skip");
                    skipHint.setTextColor(0x99FFFFFF);  // 60% white
                    skipHint.setTextSize(14f);
                    FrameLayout.LayoutParams hintLp = new FrameLayout.LayoutParams(
                            ViewGroup.LayoutParams.WRAP_CONTENT,
                            ViewGroup.LayoutParams.WRAP_CONTENT);
                    hintLp.gravity = Gravity.BOTTOM | Gravity.CENTER_HORIZONTAL;
                    hintLp.bottomMargin = 80;
                    sContainer.addView(skipHint, hintLp);

                    // Add overlay to activity (draws on top of Unity surface)
                    activity.addContentView(sContainer,
                            new FrameLayout.LayoutParams(
                                    ViewGroup.LayoutParams.MATCH_PARENT,
                                    ViewGroup.LayoutParams.MATCH_PARENT));

                    // Video completion -> cleanup
                    sVideoView.setOnCompletionListener(new MediaPlayer.OnCompletionListener() {
                        @Override
                        public void onCompletion(MediaPlayer mp) {
                            cleanup();
                        }
                    });

                    // Error -> silent fallback
                    sVideoView.setOnErrorListener(new MediaPlayer.OnErrorListener() {
                        @Override
                        public boolean onError(MediaPlayer mp, int what, int extra) {
                            cleanup();
                            return true;
                        }
                    });

                    // Tap anywhere -> skip
                    View.OnTouchListener skipTouchListener = new View.OnTouchListener() {
                        @Override
                        public boolean onTouch(View v, MotionEvent event) {
                            if (event.getAction() == MotionEvent.ACTION_UP) {
                                if (sVideoView != null) {
                                    try { sVideoView.stopPlayback(); } catch (Exception ignored) {}
                                }
                                cleanup();
                            }
                            return true;
                        }
                    };
                    sContainer.setOnTouchListener(skipTouchListener);
                    sVideoView.setOnTouchListener(skipTouchListener);

                    // Back button -> skip
                    sContainer.setOnKeyListener(new View.OnKeyListener() {
                        @Override
                        public boolean onKey(View v, int keyCode, KeyEvent event) {
                            if (keyCode == KeyEvent.KEYCODE_BACK && event.getAction() == KeyEvent.ACTION_UP) {
                                if (sVideoView != null) {
                                    try { sVideoView.stopPlayback(); } catch (Exception ignored) {}
                                }
                                cleanup();
                                return true;
                            }
                            return false;
                        }
                    });
                    sContainer.requestFocus();

                    // Start playback
                    sVideoView.setVideoURI(Uri.parse(url));
                    sVideoView.start();
                } catch (Exception e) {
                    cleanup();
                }
            }
        });
    }

    /**
     * Remove the overlay and signal native code.
     * Safe to call from any thread; ensures view operations run on UI thread.
     */
    public static void cleanup() {
        if (sCleanedUp) return;
        sCleanedUp = true;

        if (sContainer != null) {
            final View container = sContainer;
            final VideoView vv = sVideoView;
            sContainer = null;
            sVideoView = null;

            Runnable r = new Runnable() {
                @Override
                public void run() {
                    try {
                        if (vv != null) {
                            vv.stopPlayback();
                        }
                        ViewGroup parent = (ViewGroup) container.getParent();
                        if (parent != null) {
                            parent.removeView(container);
                        }
                    } catch (Exception ignored) {}
                    try {
                        nativeOnVideoComplete();
                    } catch (Exception ignored) {}
                }
            };

            if (container.getHandler() != null) {
                container.post(r);
            } else {
                r.run();
            }
        } else {
            try {
                nativeOnVideoComplete();
            } catch (Exception ignored) {}
        }
    }

    /**
     * Native callback registered by stub.cpp at DEX load time.
     */
    public static native void nativeOnVideoComplete();
}
