tell application "Mail"
  set output to ""
  repeat with acct in accounts
    repeat with mb in (every mailbox of acct)
      try
        set ms to (messages of mb whose sender contains "eversource")
        repeat with m in ms
          set subj to subject of m
          if subj contains "Statement" then
            set output to output & "=====STMT_BOUNDARY=====" & subj & linefeed & (source of m) & linefeed
          end if
        end repeat
      end try
    end repeat
  end repeat
  return output
end tell
