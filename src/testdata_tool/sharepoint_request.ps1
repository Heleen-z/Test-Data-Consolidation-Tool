$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
$request = [Console]::In.ReadToEnd() | ConvertFrom-Json
$http = $null
try {
    $http = New-Object -ComObject 'MSXML2.XMLHTTP.6.0'
    $http.open($request.method, $request.url, $false)
    foreach ($header in $request.headers.PSObject.Properties) {
        $http.setRequestHeader($header.Name, [string]$header.Value)
    }
    if ($null -eq $request.body) { $http.send() }
    else { $http.send(($request.body | ConvertTo-Json -Depth 12 -Compress)) }
    $result = @{
        status = [int]$http.status
        body = [string]$http.responseText
        retry_after = [string]$http.getResponseHeader('Retry-After')
    }
} catch {
    $result = @{ transport_error = $true }
} finally {
    if ($null -ne $http) { [void][System.Runtime.InteropServices.Marshal]::ReleaseComObject($http) }
}
[Console]::Out.Write(($result | ConvertTo-Json -Depth 12 -Compress))
