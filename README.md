<!-- Made from docs/manual.html by tools/mkreadme.py. Edit docs/manual.html, then run the tool. -->

<h1>Access Never Changes</h1>

<p class="stamp"><strong>PROPERTY OF VAULT-TEC</strong></p>

<p>Document leased for private use, billed at 75 (seventy-five) dollars, hourly.</p>

<nav aria-labelledby="contents">
<h2 id="contents">Contents</h2>
<ol>
<li><a href="#introduction">Introduction</a></li>
<li><a href="#required-equipment">Required Equipment</a></li>
<li><a href="#installation">Installation</a></li>
<li><a href="#launching-and-the-main-menu">Launching and the Main Menu</a></li>
<li><a href="#character-creation">Character Creation</a></li>
<li><a href="#navigation-exploration-and-getting-from-point-a-to-b">Navigation, Exploration, and Getting from Point A to B</a></li>
<li><a href="#the-scanner">The Scanner</a></li>
<li><a href="#menu-navigation">Menu Navigation</a></li>
<li><a href="#the-inventory">The Inventory</a></li>
<li><a href="#combat-status-and-exercising-your-right-to-sarcastically-large-firearms">Combat, Status, and Exercising Your Right to Sarcastically Large Firearms</a></li>
<li><a href="#traveling-and-the-world-screen">Traveling and the World Screen</a></li>
<li><a href="#the-pip-boy-2000">The Pip-Boy 2000</a></li>
<li><a href="#saving-loading-and-quitting">Saving, Loading, and Quitting</a></li>
<li><a href="#general-keys">General Keys</a></li>
<li><a href="#settings">Settings</a></li>
<li><a href="#translating-the-mod">Translating the Mod</a></li>
<li><a href="#disclaimers-and-things-to-keep-in-mind">Disclaimers and Things to Keep in Mind</a></li>
</ol>
</nav>

<h2 id="introduction">Introduction</h2>

<p>Welcome to Fallout 2, a post-nuclear roleplaying game. Vault-Tec has given stellar service to the American family ever since 2054, and we remain committed to being the first and last name in vault protection.</p>

<p>To this end, the Vault-Tec Board of Executives has recently been made aware of the fact that several potential Vault Dwellers suffer from a peculiar ailment known as, ‘blindness.’ After extensive investigation into this condition—including ‘voluntary’ testing to determine if blindness is proportional to a rise in communist sympathies—the Board of Executives has graciously committed the sum of 2 (two) dollars, 15 cents, and 1 pack of Fancy Lads to commissioning accessibility for 100 percent of, some, Vault-Tec products and this accompanying report.</p>

<p>You are about to enter a world of mutants, radiation, big guns, and speech synthesizers to bring the American dream forward into a brave new future. Exciting!</p>

<h2 id="required-equipment">Required Equipment</h2>

<p>In order to properly play Fallout 2, Vault-Tec recommends that you include the following items in your survival kit for best results:</p>

<ol>
<li>Fallout 2. Vault-Tec understands if the room requires a moment for the gasps to settle down. The mod has been tested on copies of Fallout 2 bought through Steam, <a href="https://store.steampowered.com/app/38410/Fallout_2_A_Post_Nuclear_Role_Playing_Game/">https://store.steampowered.com/app/38410/Fallout_2_A_Post_Nuclear_Role_Playing_Game/</a>. Vault-Tec is not held responsible for game copies acquired through other means, such as GOG, though in theory these ought to work as well.</li>
<li>The Fallout 2 Restoration Project. Vault Dwellers are to direct their Pip-Boys towards <a href="https://github.com/BGforgeNet/Fallout2_Restoration_Project">https://github.com/BGforgeNet/Fallout2_Restoration_Project</a> and follow the installation instructions therein. Unmodded and modded game copies vary widely when it comes to UI placement, resolutions, and draw sizes, and RPU also brings sfall, which the mod's in-game half runs on. Furthermore, Vault Dwellers are reminded that playing with RPU installed is a clear sign of patriotic loyalty toward the United States of America. (Please note: this also means that other overhaul mods, such as Fallout Nevada, Fallout Sonora, etc., will likely not work out of the box.)</li>
<li>A Physical Numpad. Exploration, movement, and map functions rely completely on numpad keys.</li>
<li>Vault-Tec Proprietary Accessibility Software: Access Never Changes. Which you likely already have if you are reading this document.</li>
<li>Unwavering patriotic love for the great nation of the United States of America.</li>
</ol>

<h2 id="installation">Installation</h2>

<p>Assuming that you have acquired and installed both Fallout 2 and RPU, Vault-Tec has, for your convenience, provided a mod installer. Download Access Never Changes, run it, and when asked where Fallout 2 is, direct it toward the folder where the game is installed: the one with <code>fallout2.exe</code> in it. Assuming a Steam copy, it ought to look comparable to:</p>

<pre><code>C:\Program Files (x86)\Steam\steamapps\common\Fallout 2</code></pre>

<p>Our ZAX supercomputer will put the mod in its own folder inside the game's, install all script files to their correct positions, patch ddraw.ini with the settings the mod requires, set the matching lines in <code>f2_res.ini</code> and <code>fallout2.cfg</code>, back up every changed file, and add a Fallout 2 shortcut to the Start menu, in Lights Not Included, Access Never Changes, that launches the game with the mod running.</p>

<p>Vault-Tec does not confirm or deny that this operation won't also install additional software for your own ‘safety,’ including but not limited to a keylogger calibrated to look out for search terms such as ‘socialism,’ ‘community,’ ‘tea,’ and ‘human rights.’</p>

<p>Vault-Tec. Making installation as easy as Insta-Mash since 2054.</p>

<h2 id="launching-and-the-main-menu">Launching and the Main Menu</h2>

<p>Always start the game through the Fallout 2 shortcut in the Start menu, under Lights Not Included, Access Never Changes. It starts Fallout 2 and the mod together, and closes the mod when the game closes. Starting Fallout 2 from Steam, or any other way, starts the game without the mod. Moreover, if you have installed RPU with the high-resolution patch, upon first launching the game you will be asked whether the patch ought to be disabled. The answer ought to be yes.</p>

<p>If the mod has been installed correctly, you ought to hear, ‘Fallout 2 accessibility connected.’ You will then be presented with a number of opening movies, which you may wish to observe at your leisure, or skip with Space as time permits:</p>

<ul>
<li>Firstly, you shall be met by the Interplay logo. Vault-Tec does not condone advertisement of a non-partner company and, as such, Vault Dwellers are to skip this with alacrity.</li>
<li>Secondly, the Fallout 2 first (yes, they need to be numbered) opening cutscene shall play. Vault-Tec has, as of writing, not regulated for audio description services to be applied to game cinematics and, consequently, this movie is undescribed.</li>
<li>Following this, you will be greeted with the second opening cinematic, delivered by Hakunin. Hakunin is not a registered Vault Dweller, and as such his meaningless exposition and slandering of the United States ought to be disregarded.</li>
</ul>

<p>You shall now be on the main menu, the relevant keys for which include:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">N</th><td>New game</td></tr>
<tr><th scope="row">L</th><td>Load an existing game</td></tr>
<tr><th scope="row">C</th><td>Credits</td></tr>
<tr><th scope="row">O</th><td>Options</td></tr>
<tr><th scope="row">I</th><td>Replay opening cinematics</td></tr>
<tr><th scope="row">E or Escape</th><td>Exit the program</td></tr>
</tbody>
</table>

<p>Arrow keys do not work on this menu. The mod still responds and gives you all the tools to work in these areas, however, where as arrow keys are the standard in all other menus, they are not usable here in specific. Fallout 2 renders much of its menu text as mouse-clickable illustrations. Scripts cover the conversion of these to keyboard-driven input and screen-reader usable text, however these scripts are only activated once a game is in progress. As such, these opening menus have been manually mapped out and must rely on native engine controls.</p>

<h2 id="character-creation">Character Creation</h2>

<p>Upon pressing N, Fallout 2 shall give you an option of premade characters you may wish to either start as or modify to suit your needs. Keys here include:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">Left and Right Arrows</th><td>Cycle between characters</td></tr>
<tr><th scope="row">T</th><td>Take the currently selected character</td></tr>
<tr><th scope="row">M</th><td>Modify the selected character</td></tr>
<tr><th scope="row">C</th><td>Create your own character from scratch</td></tr>
<tr><th scope="row">B</th><td>Back</td></tr>
</tbody>
</table>

<p>Either M or C shall deliver you upon the character creation screen, at which point standard menu controls, which shall be reviewed later in this manual, apply. Custom keys relevant to this screen include:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">N</th><td>Set your character’s name</td></tr>
<tr><th scope="row">A</th><td>Set your character’s age</td></tr>
<tr><th scope="row">S</th><td>Set your character’s sex</td></tr>
<tr><th scope="row">Right Arrow on traits and skills</th><td>Select traits or tag skills</td></tr>
<tr><th scope="row">Left Arrow on traits and skills</th><td>Deselect traits or untag skills</td></tr>
<tr><th scope="row">Tab</th><td>Switch categories</td></tr>
<tr><th scope="row">Enter</th><td>Finish character creation and enter the game</td></tr>
</tbody>
</table>

<h2 id="navigation-exploration-and-getting-from-point-a-to-b">Navigation, Exploration, and Getting from Point A to B</h2>

<p>Welcome to the state of California, Vault Dweller, where the American dream lives on within you and everything else is estimated by Vault-Tec to be only mildly more inconvenienced than after a typical California summer. In order to begin the process of making contact with any remaining authorities, you must be well acquainted with the (Vault-Tec understands) complicated procedure of walking. Movement in Fallout 2, like many actions, normally depends on the mouse, wherein players click on a tile within the map to direct their character to walk. Vault-Tec understands that this is impractical for blind, certainly non-communist fifth columnists. As such, here at Vault-Tec, we make the mouse come to you.</p>

<p>More specifically, Fallout 2’s map is divided into interlocking tiles known as hexes (this shall be discussed further), and your numpad moves your mouse pointer across these tiles. Controls are as follows:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">Numpad 7</th><td>Direct the cursor one hex northwest</td></tr>
<tr><th scope="row">Numpad 9</th><td>Direct the cursor one hex northeast</td></tr>
<tr><th scope="row">Numpad 4</th><td>Direct the cursor one hex west</td></tr>
<tr><th scope="row">Numpad 6</th><td>Direct the cursor one hex east</td></tr>
<tr><th scope="row">Numpad 1</th><td>Direct the cursor one hex southwest</td></tr>
<tr><th scope="row">Numpad 3</th><td>Direct the cursor one hex southeast</td></tr>
<tr><th scope="row">Numpad 5</th><td>Recenter the cursor upon your character</td></tr>
<tr><th scope="row">Numpad +</th><td>Perform a left mouse click (directs movement, or attempts to interact with any character or object on that hex)</td></tr>
<tr><th scope="row">Numpad - or M</th><td>Perform a right mouse click (switches cursor mode between the movement cursor, command cursor, and, when applicable, the targeting cursor)</td></tr>
<tr><th scope="row">Numpad .</th><td>Open the action menu</td></tr>
<tr><th scope="row">U</th><td>Use whatever is in your active hand</td></tr>
<tr><th scope="row">Shift + /</th><td>Report the distance and directions to the look cursor's hex</td></tr>
<tr><th scope="row">Control + /</th><td>Walk to the look cursor's hex; press again to stop</td></tr>
</tbody>
</table>

<p>Rather than utilizing a grid map which you may be familiar with from other top-down games—wherein a tile is one equilateral square in a grid of many, like a chessboard—Fallout 2 makes use of hex tiles. These are tiles shaped in the form of a hexagon, with the left and right sides leading straight east-west, and the other four leading in their respective diagonal positions. As such, straight north and south do not exist within Fallout 2, with each row of hexes being placed at an offset from the one atop it, so that they zigzag toward the top of the screen. In the way that Fallout 2 often lays out its structures, this is often less of an issue than it first seems, however this geometry ought to be kept in mind when exploring.</p>

<p>When walking, the mod plays a sound for each hex your character travels, and will inform you if your selected hex is out of sight, unreachable, or cannot be reliably clicked. Additionally, numbers on the number row do not function for navigation, as these are used by the game engine to arm skills. Furthermore, Fallout 2’s built in pathing algorithm abandons walking after searching 2000 tiles for a suitable route. This means that, particularly when trying to reach entities lying at the end of complex or winding routes, the native pathing algorithm gives up and will not, indeed, move you. To combat this, Vault-Tec has provided you with an onboard navigation system: Shift + / will find an available route and instruct you through it, while Control + / will walk you along it.</p>

<p>When moving the cursor, Numpad + will attempt to click upon whatever object is present on a hex and perform the default action: such as picking up loose loot, talking to NPCs, opening containers, attacking while in combat, and opening doors. Often, multiple ways of interaction may be present and/or multiple objects may share the same tile. In order to differentiate, players would normally use a right mouse click to change the behavior of their cursor between movement, interacting, and targeting, or otherwise hold down the mouse button to bring up a menu of possible options while clicking on the desired sprite.</p>

<p>The mod respects cursor changes, being as it simply simulates a mouse. However, pressing Numpad . on a hex opens a list of all entities found on that hex, allowing you to pick between them and select the desired option: talk, look, use, etc.</p>

<p>Vault Dwellers lamenting the loss of square grids ought to be reminded that the United States government has ruled that squares are the most socialist of shapes, being as they are equal and moreover resemble a book: the Little Red Book. Hexagons, Vault-Tec assures its blind Vault Dwellers, are far more patriotic as they resemble, somewhat, the American star. Do not listen to anyone dissuading you otherwise; they are clearly Chinese agents and must be reported to the local police depot at once.</p>

<h2 id="the-scanner">The Scanner</h2>

<p>Vault-Tec only wishes the best lives for its Vault Dwellers: the best version of you is the best version of the future United States. Vault-Tec also disallows, on principle, any dogs from entering vaults. Guide dogs are unexempted. Never fear, however: RobCo has included scanner functionality as standard on all Model 2000 Pip-Boys.</p>

<p>The scanner will be the primary way by which you learn of your surroundings effectively. The scanner collects all visible entities into a scrollable list, dividing them into four broad categories: scenery, items, critters, and exits. Multiples of the same type of entity (such as many trees) are presented as one entry with their count, alongside the ability to subnavigate between individual examples. Relevant controls are as follows:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">Ctrl + [ and Ctrl + ]</th><td>Switch scanner categories</td></tr>
<tr><th scope="row">[ and ]</th><td>Switch between entities per category</td></tr>
<tr><th scope="row">Shift + [ and Shift + ]</th><td>Switch between individual entries of grouped entities</td></tr>
<tr><th scope="row">/</th><td>Jump the look cursor to the selected entity</td></tr>
</tbody>
</table>

<p>The scanner respects Fallout's draw rules: things that are not visible on screen are not presented. This is with the exception of exits. To switch maps—such as from the downtown area of a settlement to peripheral surroundings—the game makes use of exit grids: hex tiles that a character must walk on to switch maps. These are always left visible in the scanner for ease of identifying where an exit to any given map is located. This, however, does not include means of switching maps that aren’t exit grids, such as manholes, ladders, etc.</p>

<p>Vault-Tec, we have your back, and your waiver of rights.</p>

<h2 id="menu-navigation">Menu Navigation</h2>

<p>In the course of reestablishing society after a nuclear exchange, you will encounter a great many menus: whether character creation, the inventory, dialogue, the Pip-Boy, the action menu, a drinks menu, etc. Rather than going through all these one at a time, the mod utilizes a general scheme applicable across menus, controls for which are as follows:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">Up and Down Arrows</th><td>Scroll through vertical lists, such as dialogue options, the inventory, the action menu, etc.</td></tr>
<tr><th scope="row">Left and Right Arrows</th><td>When applicable, either switch between different lists (such as in the inventory or barter screens) or adjust numeric amounts on sliders</td></tr>
<tr><th scope="row">Home and End</th><td>Jump to the least and the most values of numeric sliders</td></tr>
<tr><th scope="row">Backspace</th><td>Exit to the previous level in a nested menu</td></tr>
<tr><th scope="row">Enter</th><td>Confirm selection</td></tr>
<tr><th scope="row">Escape</th><td>Exit the menu entirely</td></tr>
<tr><th scope="row">Numpad /</th><td>Repeat the item you are on</td></tr>
<tr><th scope="row">Numpad .</th><td>The full description of the item you are on</td></tr>
<tr><th scope="row">F1</th><td>The keys for the screen you are on</td></tr>
</tbody>
</table>

<h2 id="the-inventory">The Inventory</h2>

<p>Vault-Tec cannot overemphasize that you will be carrying items. Many items, of many shapes, and great utility. Where will you be stashing these items while wearing Vault-Tec’s mandated skin-tight rubber jumpsuits? Vault-Tec reminds you to not ask questions you are not ready to learn the answers to.</p>

<p>Fallout 2 makes use of a two-panel inventory to store your loot and manage your equipped items. Normally, players make use of the mouse to drag items back and forth between the different sections of the inventory as the situation requires. This is replicated in the mod, the controls for which are as follows:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">I</th><td>Opens the inventory</td></tr>
<tr><th scope="row">Up and Down Arrows</th><td>Scroll vertically through lists</td></tr>
<tr><th scope="row">Left and Right Arrows</th><td>Switch between your inventory, your equipment panel, container inventory, and vendor inventories when applicable</td></tr>
<tr><th scope="row">Enter</th><td>Pick up an item from one section of the inventory, and place it in another area with the same key</td></tr>
<tr><th scope="row">Numpad .</th><td>Open the action menu on items</td></tr>
<tr><th scope="row">B</th><td>In dialogue with either a suitable NPC or companion, open barter</td></tr>
<tr><th scope="row">A</th><td>In containers, takes all items</td></tr>
<tr><th scope="row">Escape</th><td>Backs out of the inventory</td></tr>
</tbody>
</table>

<p>Your general inventory is a standard vertical list of items, not shared between the party. To the right of this, your equipment panel is divided into three slots: one each for your Armor, left hand (item 1), and right hand (item 2). To equip or make use of any item, it must be dragged into a hand slot. For example, equipping a weapon consists of pressing Enter on the item in the general inventory, switching right to the equipment panel, and pressing Enter once again on whichever hand slot you wish to equip the item to.</p>

<p>Moving a stack of more than one item asks how many, with up and Down changeing the number (with Control pressed by ten). You may use the number row to type amounts, while enter takes as configured and Escape cancels.</p>

<p>Looting from containers utilizes the same screen layout, but adds the container’s inventory as a third panel: a plain vertical list.</p>

<p>Bartering reuses the same inventory screen, but adds three new panels: the vendor’s inventory, what you are offering for trade, and what you wish to acquire from the vendor. To barter items, you must drag them from your or the vendor’s inventory into the appropriate offer panels. In barter, the value of each item is told to you, and the balance of the trade—what they want and what you are offering, and how far short you are. Pressing O makes the offer, and what the vendor did with it is read back. If the trade looks like a mistake—offering goods for nothing, or paying well over what you are getting—O says so first and waits for a second press.</p>

<h2 id="combat-status-and-exercising-your-right-to-sarcastically-large-firearms">Combat, Status, and Exercising Your Right to Sarcastically Large Firearms</h2>

<p>Can blind people make effective combatants by any metric? The answer to that question would once have likely invoked ancient pieces of mumbo-jumbo known as the Geneva Convention and the UN Convention on Human Rights. Vault-Tec is delighted to remind all Dwellers that not only is this not Geneva, but that the United Nations is no longer an institution. As such, the answer is yes. Vault-Tec believes in equal rights. To that end, Vault-Tec has taken it upon themselves to ensure that each and every blind Vault Dweller is perfectly able to keep one another honest by being heavily armed. Nothing makes a friendly community like an armed community, after all.</p>

<p>Combat in Fallout 2 takes the form of round-based turns governed by Action Points. Controls include the following:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">A</th><td>Manually trigger combat</td></tr>
<tr><th scope="row">Enter</th><td>End combat if possible</td></tr>
<tr><th scope="row">Spacebar</th><td>End your turn</td></tr>
<tr><th scope="row">B</th><td>Switch the currently active hand</td></tr>
<tr><th scope="row">N</th><td>Switch fire or attack modes of the equipped weapon</td></tr>
<tr><th scope="row">;</th><td>Report your character’s health, Action Points, armour class, level, and experience</td></tr>
<tr><th scope="row">Shift + ;</th><td>Report what is in your active hand. Firearms report how much ammunition is currently loaded</td></tr>
<tr><th scope="row">Numpad +</th><td>In combat, attacks with the active weapon using whatever mode it is set to</td></tr>
<tr><th scope="row">R</th><td>Reload the active weapon with suitable munitions</td></tr>
<tr><th scope="row">Shift + X</th><td>Order companions to give you space</td></tr>
<tr><th scope="row">Shift + R</th><td>Order companions to regroup</td></tr>
<tr><th scope="row">D</th><td>Order companions to avoid or enable automatic/burst fire</td></tr>
</tbody>
</table>

<p>With respect to man’s best friend—firearms—Fallout 2 enables you to utilize different ammo types in your weapons. In order to switch ammunition, you must enter your inventory, pick up the desired ammo box, and drop it directly onto the equipment slot of your armed weapon.</p>

<p>Firearms in Fallout 2 additionally permit you to perform ‘aimed shots,’ toggled with N. When firing such shots, the mod will present you with a list of all applicable body parts on the targeted critter, with associated percentage hit chances.</p>

<h2 id="traveling-and-the-world-screen">Traveling and the World Screen</h2>

<p>There are many people to meet, things to do, and questionable substances to consume in the world of Fallout 2 (Vault-Tec does not take responsibility for any extraneous toes or extend vault residency to unapproved third-party offspring). As such, you will have to travel between settlements and points of interest by utilizing the world map.</p>

<p>The world map is entered via a standard exit grid on applicable maps, and is represented as a square grid of locations. Controls are as follows:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">Numpad 8</th><td>Move one tile north</td></tr>
<tr><th scope="row">Numpad 2</th><td>Move one tile south</td></tr>
<tr><th scope="row">Numpad 4</th><td>Move one tile west</td></tr>
<tr><th scope="row">Numpad 6</th><td>Move one tile east</td></tr>
<tr><th scope="row">Numpad 7</th><td>Move one tile north west</td></tr>
<tr><th scope="row">Numpad 9</th><td>Move one tile north east</td></tr>
<tr><th scope="row">Numpad 1</th><td>Move one tile south west</td></tr>
<tr><th scope="row">Numpad 3</th><td>Move one tile south east</td></tr>
<tr><th scope="row">Numpad 5</th><td>Recenter on your character</td></tr>
<tr><th scope="row">[ and ]</th><td>Scroll between a list of all known points of interest</td></tr>
<tr><th scope="row">/</th><td>Jump the cursor to the selected point of interest</td></tr>
<tr><th scope="row">Enter</th><td>Begin walking toward the designated map tile or enter the place you are standing on</td></tr>
<tr><th scope="row">T</th><td>Bring up the town map of a place you have already been inside: a list of numbered entrances, chosen with the number keys</td></tr>
</tbody>
</table>

<p>In contrast to the local map, the world map does not use hex tiles. Rather, it is a standard orthogonal square grid of tiles and…</p>

<p>(Editorial comment: The fuck, people? First you tell me squares are commies, now we have squares for the world map. Are cartographers communists? Is all of California communist? Am I a communist?)</p>

<p>Vault-Tec encourages all Vault Dwellers to observe this map at the prescribed jaunty head tilt of 45 (forty-five) degrees so as to make the squares look like diamonds. Diamonds mean money. Money means happiness. Happiness means America.</p>

<h2 id="the-pip-boy-2000">The Pip-Boy 2000</h2>

<p>Vault-Tec’s long and healthy relationship with RobCo Industries means that accessibility is provided to your standard Pip-Boy as well, controls for which include:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">P</th><td>Open the Pip-Boy from the explore view</td></tr>
<tr><th scope="row">Z</th><td>Open the Pip-Boy’s alarm menu directly from the explore view</td></tr>
</tbody>
</table>

<p>The Pip-Boy is a standard menu, operation of which is outlined above. One thing of note is that the Pip-Boy normally gives the ability to view automaps: remembered outlines of all maps you have visited. As there is no useful way to translate such maps, which are pictures, to the screen reader medium, Vault-Tec advises you to disregard this button. This button has been deemed a transgression and informed to RobCo R&amp;D. This button lies. Vault-Tec does not lie. Keep in mind as well that Tab from the explore view also opens the local area’s automap which is similarly non-useful. Another press of Tab will return you to the exploration view.</p>

<h2 id="saving-loading-and-quitting">Saving, Loading, and Quitting</h2>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">F6</th><td>Quick save</td></tr>
<tr><th scope="row">F7</th><td>Quick load</td></tr>
<tr><th scope="row">Escape</th><td>Bring up the game's pause menu</td></tr>
<tr><th scope="row">Ctrl + X</th><td>Quit the game</td></tr>
</tbody>
</table>

<p>On the save and load screens, saves are grouped into lists of 10. Up and Down walk the slots and Left and Right turn the pages to extra save slots.</p>

<h2 id="general-keys">General Keys</h2>

<p>Either natively or via the mod, Fallout 2 has a number of other keybinds that Vault-Tec have insured work in service of all Vault Dwellers. These include:</p>

<table>
<thead><tr><th scope="col">Key</th><th scope="col">Action</th></tr></thead>
<tbody>
<tr><th scope="row">1-8</th><td>Arm respective skills: sneak, lock picking, stealing, traps, first aid, doctor, science, and repair. Using Numpad + on any hex will attempt to deploy the armed skill, otherwise skills may be invoked on specific targets via the action menu</td></tr>
<tr><th scope="row">Shift + 1</th><td>Report the light level on the currently selected hex</td></tr>
<tr><th scope="row">Shift + , and .</th><td>Scroll through a message log of all log text and floating text popups, retaining the last 300</td></tr>
<tr><th scope="row">S</th><td>Open the Skilldex, listing your skills, their keybinds, and their current percentages</td></tr>
<tr><th scope="row">C</th><td>Open the character sheet. While in this screen, left and right arrows on your skills will assign any level up points you have to spend, and Enter will confirm any changes</td></tr>
</tbody>
</table>

<h2 id="settings">Settings</h2>

<p>The mod's settings live in <code>access.ini</code>, in the <code>Access Never Changes</code> folder inside the game's. The Settings shortcut in the Start menu, under Lights Not Included, Access Never Changes, opens it in Notepad. Every setting is explained in the file itself:</p>

<ul>
<li>which voice to use: your screen reader, or the Windows voice;</li>
<li>which language to speak (see below);</li>
<li>whether to keep speaking when the game is not the window in front;</li>
<li>the sound for every hex you walk;</li>
<li>if the mod's own keys are on or off;</li>
<li>whether the mod closes when the game does.</li>
</ul>

<p>Save the file and start the mod again for a change to take effect.</p>

<h2 id="translating-the-mod">Translating the Mod</h2>

<p>Most of what you hear in a translated game is already in your language. Item names, dialogue, skills, perks, etc. all come from the game's own files. Where the mod has been forced to put in its own strings, either because the game text is unreachable or shown as graphics, those are in <code>lang\english.ini</code> in the mod's folder, and a translation is a copy of that file.</p>

<ol>
<li>Copy <code>lang\english.ini</code> to a new file named after your language the way the game's <code>fallout2.cfg</code> spells it: <code>german.ini</code>, <code>french.ini</code>, <code>polish.ini</code>, <code>russian.ini</code>.</li>
<li>Change the words after each <code>=</code>. Leave the part before <code>=</code> alone.</li>
<li>Keep every word in braces, such as <code>{count}</code> or <code>{place}</code>, spelt exactly as it is. The mod fills those in. You can move them anywhere in the line.</li>
<li>Save the file as UTF-8.</li>
</ol>

<p>With <code>language = auto</code> in <code>access.ini</code>, the default, the mod speaks whichever file matches the game's language. Set <code>language = german</code> to choose one yourself.</p>

<p>Some things to know about the file:</p>

<ul>
<li>Sections group the words by where they are heard: <code>[combat]</code>, <code>[worldmap]</code>, <code>[inventory]</code> and so on. <code>[keys]</code> and <code>[help]</code> are what F1 says, and <code>[screen]</code> names each screen in it.</li>
<li>Some keys are made from English, such as <code>help.move_the_look_cursor_5_comes_back_to_you</code>. If that English changes in a later version, the key changes with it, and your old line is ignored rather than saying something out of date.</li>
<li>Counts come in pairs: <code>one_hex = 1 hex</code> and <code>hexes = {count} hexes</code>. Languages with more than two plural forms, such as Polish or Russian, have to pick the form that fits best for now.</li>
<li>Some sentences are put together from pieces, such as a name followed by <code>{index} of {total}</code>. Translate each piece so it reads naturally on its own.</li>
</ul>

<h2 id="disclaimers-and-things-to-keep-in-mind">Disclaimers and Things to Keep in Mind</h2>

<p>Fallout 2 is, at its core, a game built in the year of our God-fearing, beer-drinking, red, white, and blue-flying United States of America, 1998. The game was also, from inception, always designed for a mouse. As such, a few things ought to be kept in mind as you venture forth (all litigations based on death or harm will be attributed to a disregard toward this section of the document; automatic agreement and acknowledgement have been registered as you arrive on this page).</p>

<p>Firstly, keep in mind that buildings and structures are very rarely, if ever, placed in straight lines. As discussed, Fallout 2 uses a zigzagging hex grid and, being such, buildings are often placed on a diagonal facing. The front walls of buildings, for example, will often trace from top-left to bottom-right. This is why 6-way hex navigation is often not as much of a problem as it originally seems, as most times you will want to navigate on the diagonal anyway.</p>

<p>Secondly, remember that Numpad + in explore and Enter in the inventory are piloting a mouse pointer. The mod attempts to place the pointer upon whatever it is that you wish to click; however, Fallout 2 often draws sprites in such a way that they may overlap entities or hexes. Vault-Tec proprietary software ensures that, even with this in mind, hit rates are quite good. However, if the mod reports that a hex cannot be clicked for whatever reason, either try again, reposition one or two hexes, or, more reliably, use the action menu (Numpad .). The action menu directs operations straight to the game engine without recourse to the mouse, and as such, will practically always succeed. The only place where the action menu does not apply is the inventory, as this would break time and space and permit Vault Dwellers to move objects without respecting the laws of time and Action Points. Consequently, inventory management relies on the mouse pointer. As the inventory is a static list, the mouse here is quite reliable, though it must be noted that moving items might take a second or two as the mod locates where on the screen particular slots are drawn.</p>

<p>Vault-Tec reminds its Vault Dwellers that the department of future-tec is in correspondence with the Chryslus Motors company to introduce assistive technology in Highwayman model vehicles. As of yet, this is 100 percent partly completed and use of the Highwayman in game ought not to be considered supported yet.</p>
