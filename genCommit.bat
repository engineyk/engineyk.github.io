set curDir="%~dp0%"
cd /d %curDir%

python gen_resources.py
git add ./
git commit -m "m"
git push -u origin main
pause