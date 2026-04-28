set curDir=%~dp0%
cd /d %curDir%

python gen_resources.py --input "%curDir%/_posts" --output "%curDir%/resources.html"
pause