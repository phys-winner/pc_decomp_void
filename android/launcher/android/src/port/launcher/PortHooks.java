package port.launcher;

import android.content.Context;
import android.content.Intent;
import java.io.File;
import java.util.Collections;
import java.util.List;

/** What only the game knows, for the launcher: a class of the game named by port.json's
 *  "app.hooks" implements it (all methods are optional). The launcher's process loads it: it must
 *  not touch the game's activity or native library. */
public interface PortHooks {
    /** A reason an optional choice cannot be used yet; null when its files are available. */
    default String optionProblem(Context context, String key, String value) { return null; }
    /** Paths of a part, relative to its folder, which the game also needs and which are missing
     *  there now, beyond port.json's "required": what depends on the game's own settings (UT3: the
     *  language chosen in its settings). Empty when nothing is missing. */
    default List<String> missing(Context context, String distribution, String part, File folder) { return Collections.emptyList(); }

    /** Refuses an incompatible installation destination before any files are changed; null accepts it. */
    default String installationProblem(Context context, String distribution, String part, File folder) { return null; }

    /** Full original-input verification, on an import/selection worker before the new folder is
     * committed. A game can hash its small EXE/DLL here; this never runs on the UI thread. */
    default void verifyInstallation(Context context, String distribution, String part, File folder) throws java.io.IOException { }

    /** The renderer the game would start with when the game keeps the choice in its own settings
     *  (an in-game options page); null: the launcher keeps it. */
    default String renderer(Context context) { return null; }

    /** Stores the player's renderer where the game reads it. */
    default void setRenderer(Context context, String mode) { }

    /** Adds the game's own extras to the intent that starts a distribution. */
    default void prepare(Context context, String distribution, Intent intent) { }

    /** Once per process, before the launcher or Launch.attach reads the player's choices: a game
     *  that had a launcher of its own hands its settings over here with Launch.adopt (Heroes V: the
     *  game folders and options its old launcher kept), so that an update keeps the player's setup. */
    default void migrate(Context context) { }

    /** Loads the hooks of port.json, or the defaults. */
    static PortHooks of(Context context) {
        String name = Spec.get(context).hooks;
        if (!name.isEmpty()) {
            try {
                return (PortHooks) Class.forName(name).getDeclaredConstructor().newInstance();
            } catch (ReflectiveOperationException | ClassCastException e) {
                android.util.Log.e("Launcher", "hooks " + name + ": " + e);
            }
        }
        return new PortHooks() { };
    }
}
