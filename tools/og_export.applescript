-- Export .graffle files to PDF/PNG with OmniGraffle itself (macOS only).
-- Usage:  osascript tools/og_export.applescript /abs/in.graffle /abs/out.pdf [scale]
--         (format is taken from the output extension: pdf | png | svg | jpg)
-- NOTE: written against the OmniGraffle 7 AppleScript dictionary; not testable on Linux.
on run argv
	set inPath to item 1 of argv
	set outPath to item 2 of argv
	set scaleValue to 2.0
	if (count of argv) > 2 then set scaleValue to (item 3 of argv) as real
	set ext to do shell script "echo " & quoted form of outPath & " | sed 's/.*\\.//' | tr a-z A-Z"
	if ext is "JPG" then set ext to "JPEG"
	tell application "OmniGraffle"
		set theDoc to open (POSIX file inPath)
		delay 0.5
		tell current export settings
			set area type to all graphics
			set draws background to false
			set export scale to scaleValue
			set include border to true
			set border amount to 8
		end tell
		save theDoc as ext in (POSIX file outPath)
		close theDoc saving no
	end tell
	return outPath
end run
