# DaVinci-Resolve-Project-File-to-Blender-File
(beginner in GitHub) i asked AI to help for coding in Blender Python to code that converts .drp file into .blend. but, theres alot of issue and did not convert correctly, said that the XML File cannot parse the .drp, im asking for help to fix this code, because the AI i used is exclusive and need to pay for usage.

you need to run the converter.py into the powershell, then type: cd "C:\Users\<YOUR NAME>\Downloads" or wherever you put the converter.py file in your system, then also put your .drp file in the same directory as converter.py, i suggest creating a folder for that file for no confusion.
then in powershell, type: & "C:\Program Files\Blender Foundation\Blender X.X\blender.exe" -b -P converter.py -- YOUR_FILE.drp output.blend --verbose (make sure to change the "X.X" in "Blender X.X" to the current version of your Blender, then at "YOUR_FILE.drp", change it to the name of your .drp file (e.g.: davincifile.drp). 
Name the OUTPUT.blend however you like, and you SUPPOSED to see a .blend file with the name you gave in "OUTPUT.blend"

but it has errors: XML Parsing error: not-well formed (invalid token): line 1, column 2
                  Failed to parse DRT file.

i need your help
