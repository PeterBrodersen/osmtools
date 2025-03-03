<?php
// Husk: Sæt BANE og DESCRIPTION alt efter hvilken bane, der er tale om, og om banen eksisterer
// Bagefter: Brug QuickStatements: https://quickstatements.toolforge.org/#/
#define("BANE","Q115407963");
define("DESCRIPTIONDK","tidligere jernbanestation i Denmark");
define("DESCRIPTIONEN","former railway station in Denmark");
#define("DESCRIPTION","railway station in Denmark'");
$lineurl = $_GET['lineurl'];
$lineq = $_GET['lineq'];
$stationurl = $_GET['stationurl'];
$result = '';
if ($lineurl) {
	$result = checkLine($lineurl, $lineq);
	
}
if ($stationurl) {
	$result = checkURL($stationurl);
}

function predie($text) {
	header("Content-Type: text/plain");
	print $text;
	exit;
}

function checkLine ($url, $lineq) {
	#$stationsPattern = "_<td><a class='text-primary' href='(vis.station.php.*?)'_";
	$stationsPattern = '_<td><a class="text-underline-hover" href="(vis.station.php.*?)"_';
	$stationsPattern = "_<td><a class='text-underline-hover' href='(vis.station.php.*?)'_";
	$result = '';
	if (! preg_match('_^https://_', $url) ) {
		$url = 'https://' . $url;
	}
	$content = file_get_contents($url);
	if (!$content) {
		return 'Error: No line content';
	}
	if ( ! preg_match_all($stationsPattern, $content, $match) ) {
		return 'Error: No stations found';
	}
	foreach($match[1] AS $urlpart) {
		$url = 'https://danskejernbaner.dk/' . htmlspecialchars_decode($urlpart);
		$result .= checkURL($url, $lineq) . "\n";
	}

	return $result;

}

function checkURL ($url, $lineq = "") {
	$start = '';
	$end = '';
	$bane = $lineq;
	$descriptiondk = DESCRIPTIONDK;
	$descriptionen = DESCRIPTIONEN;
	if (! $url) {
		return '';
	}
	if (! preg_match('_^https://_', $url) ) {
		$url = 'https://' . $url;
	}
	$content = file_get_contents($url);
#	print "<pre>" . htmlspecialchars($content) . "</pre>";
	if (!$content) {
		return 'Error: No content';
	}
	$result = "CREATE\n";
	if ( ! preg_match('_<title>(.*?), en artikel.*?</title>_', $content, $match)) {
		return 'Error: No name';
	}
	$name = trim($match[1]);
	if ( ! preg_match('_<tr><td>Åbnet</td><td>(\d+)(\.(\d\d)\.(\d\d))?</td></tr>_', $content, $match) ) {
#		return 'Error: No start date';
	} else {
		$year = $match[1];
		$month = $match[3];
		$day = $match[4];
		$start = '+' . $year . '-' . ($month ? $month : '00') . '-' . ($day ? $day : '00') .'T00:00:00Z/' . ($month == '' ? 9 : 11);
	}
	if ( ! preg_match('_<tr><td>Nedlagt</td><td>(\d+)(\.(\d\d)\.(\d\d))?</td></tr>_', $content, $match) ) {
#		return 'Error: No end date';
	} else {
		$year = $match[1];
		$month = $match[3];
		$day = $match[4];
		$end = '+' . $year . '-' . ($month ? $month : '00') . '-' . ($day ? $day : '00') .'T00:00:00Z/' . ($month == '' ? 9 : 11);
	}
	if ( ! preg_match('_<tr><td>GPS koordinater</td><td>(\d+\.\d+,\d+\.\d+)</td></tr>_', $content, $match) ) {
		return 'Error: No coordinates';
	}
	$coordinates = '@' . str_replace(',','/',$match[1]);
	$result .= "LAST\tLen\t\"" . $name . "\"\n";
	$result .= "LAST\tLda\t\"" . $name . "\"\n";
	$result .= "LAST\tDen\t\"" . $descriptionen . "\"\n";
	$result .= "LAST\tDda\t\"" . $descriptiondk . "\"\n";
	$result .= "LAST\tP31\tQ4663385\tS854\t\"" . htmlspecialchars($url) . "\"\n";
	$result .= "LAST\tP17\tQ35\n";
	if ($bane) {
		$result .= "LAST\tP81\t" . $bane . "\n";
	}
	if ($start) $result .= "LAST\tP1619\t" . $start . "\n";
	if ($end) $result .= "LAST\tP3999\t" . $end . "\n";
	$result .= "LAST\tP625\t" . $coordinates . "\n";

	return $result;
}
?>
<!DOCTYPE html>
<html>
<head>
<title>Station converter to Wikidata</title>
<script>
function updateQuickStatementsLink(quickStatements) {
    let encodedStatements = encodeURIComponent(quickStatements).replace(/%0A/g, '%7C%7C');
    let quickStatementsLink = `https://quickstatements.toolforge.org/#/v1=${encodedStatements}`;
    document.getElementById('quickStatementsLink').href = quickStatementsLink;
}

function updateQSLFromForm() {
	const value = document.getElementById('quickStatements').value;
	return updateQuickStatementsLink(value);
}
</script>
</head>
<body>
<form action="station.php" method="get">
<div>
Enter URL for line: <input type="url" name="lineurl" size="100" value="<?php print htmlspecialchars($lineurl); ?>"><br>
Enter line item: <input type="text" name="lineq" pattern="^Q\d+$" placeholder="Q115408461" value="<?php print htmlspecialchars($lineq); ?>"><br>
<input type="submit">
</div>
</form>
<div>
or
</div>
<form>
<div>
Enter URL for station: <input type="url" name="stationurl" size="100" value="<?php print htmlspecialchars($stationurl); ?>"><input type="submit">
</div>
</form>
<?php
if ($result) {
?>
<p></p>
<div>
<textarea rows="10" cols="150" onchange="updateQuickStatementsLink(this.value);" id="quickStatements">
<?php print $result; ?>
</textarea>
<?php
}
?>
<div>
<a href="https://quickstatements.toolforge.org/#/" id="quickStatementsLink">QuickStatements Form</a>
</div>
<p>
<a href="https://quickstatements.toolforge.org/#/">QuickStatements Main Page</a>
</p>
<script>
updateQSLFromForm();
</script>
</body>
</html>

