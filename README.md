# **Thank you for choosing PY\_30's Roblox <-> Vortex Converter (v0.4)**

**Full Toolchain Documentation:**



## **| WHAT THIS DOES**

* Using this, in seconds, you can transition your Roblox places into a Vortex place *(the other way around too)*
* It cleanly converts: Parts, TrussParts, Models, Scripts *(excluding ModuleScripts)*, Remote Events / Function, Bindable Events, SpawnLocations 
* What does **NOT** convert: currently, **Vortex > Roblox** converts full games, although **Roblox > Vortex** converts features only available in Vortex v0.4.
* Use this as more of a test, as of v0.4, Vortex is very limited, and does not let you create great games compared to Roblox. [Scripting in Vortex](https://create.playvortex.io/) is also very limited. Do not use this to switch engines *(yet)*.



## **| SETUP:**

**STEP 1:** Install Python.

* Download Python from:

    [https://www.python.org/downloads/](https://www.python.org/downloads/)

* On Windows, tick "Add Python to PATH" during installation



**STEP 2:** Install the required Python library:

* Open a terminal (Command Prompt / PowerShell / Terminal) and run:

  pip install zstandard

* Its used to decompress **.vrtx** files



**STEP 3:** Verify installation (optional)

* Run:

    **py -c "import zstandard; print(zstandard.\_\_version\_\_)"**



## **| HOW TO USE: *(in case anything doesn't work view troubleshooting written below)***

### ***a) Roblox -> Vortex***

1. Save your Roblox project as a **.rblxl** file.
2. Insert it into a folder called *"TargetFiles"* located in the same folder as this file.
3. Open **PowerShell** and open this folder's directory. *(ex. **cd "C:\\Users\\user\\Downloads\\vortex-converter-main"**)*
4. Using **PowerShell**, run **ConvertToVortex.py** and pass in your file's name. *(ex. **py ConvertToVortex.py myGame.rbxlx**)*
5. A new file should appear named by your target file, this time in **.vrtx**. Open this file directly in **Vortex Studio**. *In case anything fails, follow printed instructions, in case it errors, report your bug directly in the forum.*
6. Enjoy!


### ***b) Vortex -> Roblox***

1. Save your Vortex project, and insert it into a folder called *"TargetFiles"* located in the same folder as this file.
2. Open **PowerShell** and open this folder's directory. *(ex. **cd "C:\\Users\\user\\Downloads\\vortex-converter-main"**)*
3. Using **PowerShell**, run **ConvertToRoblox.py** and pass in your file's name. *(ex. **py ConvertToRoblox.py myGame.vrtx**)*
4. A new file should appear named by your target file, this time in **.rbxlx**. Open this file using **Roblox Studio**. *In case anything fails, follow printed instructions, in case it errors, report your bug directly in the forum.*
5. To prevent any publishing issues: before editing, save your file as a default **.rbxl** file.
6. Enjoy!



## **| ADVANCED**

### a) Optional Arguments

* **--verbose** or **-v** - Print full output from each underlying converter script instead of hiding it
* **--keep-json** - Save a **.json** file when the conversion finishes showing how every instance is ported to Vortex
* **[output-file]** - Second positional arg: put the output somewhere other than next to the input


### b) Examples

* **py ConvertToRoblox.py myscene.vrtx**
* **py ConvertToRoblox.py myscene.vrtx --verbose**
* **py ConvertToRoblox.py myscene.vrtx --keep-json**
* **py ConvertToRoblox.py myscene.vrtx custom_name.rbxlx --verbose --keep-json**
* **py ConvertToRoblox.py**                           (auto-picks if TargetFiles has one file)
* **py ConvertToRoblox.py**                           (shows menu if multiple files present)


## **| TROUBLESHOOTING**

* If using "py" in terminal doesn't work, try "python" or "python3"
* If zstandard won't install, try "pip3 install zstandard".
* Trying to convert outdated Vortex files could fail. If that happens, open your vortex file, make a small change (like moving a part) and save the file.
* Trying to convert newer Vortex files than designed will fail. If that happens, please download the newer version, you can find every version uploaded in the same forum page.

