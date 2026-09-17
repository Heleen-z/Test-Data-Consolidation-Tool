Attribute VB_Name = "Bridge"
Option Explicit

Public Function BridgeVersion() As String
    BridgeVersion = "1"
End Function

' Request: method, URL, digest, ASCII JSON. Response: status, Retry-After, UTF-8 body.
Public Sub DoRequest(ByVal requestPath As String, ByVal responsePath As String)
    Dim fileNo As Integer, opened As Boolean
    Dim method As String, targetUrl As String, digest As String, body As String
    Dim http As Object, message As String, retryAfter As String
    On Error GoTo Failed
    fileNo = FreeFile
    Open requestPath For Input As #fileNo
    opened = True
    Line Input #fileNo, method
    Line Input #fileNo, targetUrl
    Line Input #fileNo, digest
    Line Input #fileNo, body
    Close #fileNo
    opened = False
    Set http = CreateObject("MSXML2.XMLHTTP.6.0")
    http.Open method, targetUrl, False
    http.setRequestHeader "Accept", "application/json;odata=verbose"
    http.setRequestHeader "Content-Type", "application/json;odata=verbose"
    If digest <> "-" Then http.setRequestHeader "X-RequestDigest", digest
    If body = "-" Then
        http.Send
    Else
        http.Send body
    End If
    retryAfter = http.getResponseHeader("Retry-After")
    WriteUtf8 responsePath, CStr(http.Status) & vbLf & retryAfter & vbLf & http.responseText
    Exit Sub
Failed:
    message = CStr(Err.Number)
    On Error Resume Next
    If opened Then Close #fileNo
    WriteUtf8 responsePath, "-1" & vbLf & vbLf & "bridge_transport_error:" & message
End Sub

Private Sub WriteUtf8(ByVal targetPath As String, ByVal content As String)
    Dim stream As Object
    Set stream = CreateObject("ADODB.Stream")
    stream.Type = 2
    stream.Charset = "utf-8"
    stream.Open
    stream.WriteText content
    stream.SaveToFile targetPath, 2
    stream.Close
End Sub
