/*
 * keys.h  --  the mod's own keys, as the player set them in keys.ini.
 *
 * The Python side reads keys.ini, checks it, and writes what it found to
 * KEYS_INI as plain numbers every time it starts: the DirectInput scancode,
 * plus KEY_SHIFT if Shift is part of it and KEY_CTRL if Control is. A script
 * cannot sensibly read "Right bracket" for itself, and doing the checking once,
 * in one place, is what keeps the two halves agreeing on what a key means.
 *
 * Read once, at start. A number that is missing -- no file yet, or a mod older
 * than the file -- is the key the script always had, so a script never ends up
 * with no key at all.
 *
 * **A key is matched with the modifiers it was PRESSED with, on the way up as
 * well.** sfall wants a swallowed key swallowed on both halves of the event,
 * and a player who lets go of Shift before the bracket would otherwise send a
 * release that looks like a plain bracket -- a different binding, or none,
 * reaching the engine for a key whose press it never saw. key_note keeps what
 * each key was pressed as, and the release is judged by that.
 */

#define KEYS_INI    "Access Never Changes/script_keys.ini|keys|"
#define KEY_SHIFT   (256)
#define KEY_CTRL    (512)

variable g_kheld;      // what each scancode was pressed as, by scancode
variable g_kfull;      // the key in hand, with its modifiers

variable g_k_nw;
variable g_k_ne;
variable g_k_w;
variable g_k_e;
variable g_k_sw;
variable g_k_se;
variable g_k_n;
variable g_k_s;
variable g_k_home;
variable g_k_kind_prev;
variable g_k_kind_next;
variable g_k_one_prev;
variable g_k_one_next;
variable g_k_cat_prev;
variable g_k_cat_next;
variable g_k_scan_go;
variable g_k_route_say;
variable g_k_route_walk;
variable g_k_status;
variable g_k_weapon;
variable g_k_use;
variable g_k_light;
variable g_k_menu;
variable g_k_help;
variable g_k_log_older;
variable g_k_log_newer;

procedure key_setting(variable name, variable fallback) begin
   variable v := get_ini_setting(KEYS_INI + name);
   if (v <= 0) then return fallback;
   return v;
end

procedure keys_load begin
   g_kheld := create_array_list(256);
   g_k_nw         := key_setting("cursor_northwest", DIK_NUMPAD7);
   g_k_ne         := key_setting("cursor_northeast", DIK_NUMPAD9);
   g_k_w          := key_setting("cursor_west", DIK_NUMPAD4);
   g_k_e          := key_setting("cursor_east", DIK_NUMPAD6);
   g_k_sw         := key_setting("cursor_southwest", DIK_NUMPAD1);
   g_k_se         := key_setting("cursor_southeast", DIK_NUMPAD3);
   g_k_n          := key_setting("cursor_north", DIK_NUMPAD8);
   g_k_s          := key_setting("cursor_south", DIK_NUMPAD2);
   g_k_home       := key_setting("cursor_home", DIK_NUMPAD5);
   g_k_kind_prev  := key_setting("scan_kind_previous", DIK_LBRACKET);
   g_k_kind_next  := key_setting("scan_kind_next", DIK_RBRACKET);
   g_k_one_prev   := key_setting("scan_one_previous", DIK_LBRACKET + KEY_SHIFT);
   g_k_one_next   := key_setting("scan_one_next", DIK_RBRACKET + KEY_SHIFT);
   g_k_cat_prev   := key_setting("scan_category_previous", DIK_LBRACKET + KEY_CTRL);
   g_k_cat_next   := key_setting("scan_category_next", DIK_RBRACKET + KEY_CTRL);
   g_k_scan_go    := key_setting("scan_go", DIK_SLASH);
   g_k_route_say  := key_setting("route_say", DIK_SLASH + KEY_SHIFT);
   g_k_route_walk := key_setting("route_walk", DIK_SLASH + KEY_CTRL);
   g_k_status     := key_setting("status", DIK_SEMICOLON);
   g_k_weapon     := key_setting("weapon", DIK_SEMICOLON + KEY_SHIFT);
   g_k_use        := key_setting("use_hand", DIK_U);
   g_k_light      := key_setting("light", DIK_1 + KEY_SHIFT);
   g_k_menu       := key_setting("menu", DIK_DECIMAL);
   g_k_help       := key_setting("help", DIK_F1);
   g_k_log_older  := key_setting("log_older", DIK_COMMA + KEY_SHIFT);
   g_k_log_newer  := key_setting("log_newer", DIK_PERIOD + KEY_SHIFT);
   debug_msg("KEYS:loaded " + g_k_nw + "|" + g_k_kind_next + "|" + g_k_menu + "|");
end

/*
 * The key in hand, as a number to compare against the g_k_ values: called
 * once at the top of on_key, before anything asks `bound`.
 */
procedure key_note(variable key, variable pressed) begin
   variable full := key;
   if (key < 0 or key >= 256 or not g_kheld) then begin
      g_kfull := key;
      return;
   end
   if (pressed) then begin
      if (key_pressed(DIK_LSHIFT) or key_pressed(DIK_RSHIFT)) then
         full := full + KEY_SHIFT;
      if (key_pressed(DIK_LCONTROL) or key_pressed(DIK_RCONTROL)) then
         full := full + KEY_CTRL;
      set_array(g_kheld, key, full);
   end else if (get_array(g_kheld, key) > 0) then begin
      full := get_array(g_kheld, key);
   end
   g_kfull := full;
end

procedure bound(variable code) begin
   return (g_kfull == code);
end

// Any of the look cursor's keys, which a list on screen takes so the cursor
// does not wander under it.
procedure cursor_key begin
   return (bound(g_k_nw) or bound(g_k_ne) or bound(g_k_w) or bound(g_k_e)
        or bound(g_k_sw) or bound(g_k_se) or bound(g_k_n) or bound(g_k_s)
        or bound(g_k_home));
end
