package org.thevoid.port;

import android.app.Activity;
import android.content.Intent;
import android.os.Bundle;

/** Runs in its own process (AndroidManifest.xml): ends the game's process
 *  and starts the game again, so settings read at start apply. */
public final class RestartActivity extends Activity {
    static final String PID = "pid";
    static final String LAUNCHER = "launcher";

    @Override protected void onCreate(Bundle state) {
        super.onCreate(state);
        int pid = getIntent().getIntExtra(PID, -1);
        if (pid > 0) android.os.Process.killProcess(pid);
        Intent i = new Intent(this, getIntent().getBooleanExtra(LAUNCHER, false) ? Launcher.class : GameActivity.class);
        i.putExtra(Launcher.EXTRA_GAME, getIntent().getStringExtra(Launcher.EXTRA_GAME));
        i.putExtra("userdata", getIntent().getStringExtra("userdata"));
        i.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TASK);
        startActivity(i);
        finish();
        Runtime.getRuntime().exit(0);
    }
}
