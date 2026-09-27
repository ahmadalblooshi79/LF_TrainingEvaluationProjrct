import 'dart:convert';
import 'dart:typed_data';

import 'package:archive/archive.dart';

/// Minimal XLSX writer (UTF-8 inline strings). No extra spreadsheet engine.
Uint8List buildSimpleXlsx(
  Map<String, List<List<String>>> sheets, {
  Set<String> hiddenSheetNames = const {},
}) {
  final archive = Archive();
  archive.addFile(
    ArchiveFile(
      '[Content_Types].xml',
      0,
      utf8.encode(_contentTypes(sheets.length)),
    ),
  );
  archive.addFile(
    ArchiveFile('_rels/.rels', 0, utf8.encode(_relsRoot())),
  );
  archive.addFile(
    ArchiveFile(
      'xl/workbook.xml',
      0,
      utf8.encode(_workbook(sheets.keys.toList(), hiddenSheetNames)),
    ),
  );
  archive.addFile(
    ArchiveFile(
      'xl/_rels/workbook.xml.rels',
      0,
      utf8.encode(_workbookRels(sheets.length)),
    ),
  );
  archive.addFile(ArchiveFile('xl/styles.xml', 0, utf8.encode(_styles())));
  var i = 1;
  for (final rows in sheets.values) {
    archive.addFile(
      ArchiveFile(
        'xl/worksheets/sheet$i.xml',
        0,
        utf8.encode(_sheetXml(rows)),
      ),
    );
    i++;
  }
  final encoded = ZipEncoder().encode(archive);
  return Uint8List.fromList(encoded ?? const <int>[]);
}

String _xml(String s) {
  return s
      .replaceAll('&', '&amp;')
      .replaceAll('<', '&lt;')
      .replaceAll('>', '&gt;')
      .replaceAll('"', '&quot;')
      .replaceAll("'", '&apos;')
      .replaceAll(RegExp(r'[\x00-\x08\x0B\x0C\x0E-\x1F]'), '');
}

String _colName(int index) {
  var n = index;
  var s = '';
  while (n > 0) {
    n--;
    s = String.fromCharCode(65 + (n % 26)) + s;
    n ~/= 26;
  }
  return s;
}

String _sheetXml(List<List<String>> rows) {
  final buf = StringBuffer();
  buf.write(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<sheetData>',
  );
  for (var r = 0; r < rows.length; r++) {
    buf.write('<row r="${r + 1}">');
    final cols = rows[r];
    for (var c = 0; c < cols.length; c++) {
      final ref = '${_colName(c + 1)}${r + 1}';
      buf.write(
        '<c r="$ref" t="inlineStr"><is><t xml:space="preserve">${_xml(cols[c])}</t></is></c>',
      );
    }
    buf.write('</row>');
  }
  buf.write('</sheetData></worksheet>');
  return buf.toString();
}

String _contentTypes(int sheetCount) {
  final buf = StringBuffer();
  buf.write(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
  );
  for (var i = 1; i <= sheetCount; i++) {
    buf.write(
      '<Override PartName="/xl/worksheets/sheet$i.xml" '
      'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>',
    );
  }
  buf.write('</Types>');
  return buf.toString();
}

String _relsRoot() =>
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    '</Relationships>';

String _workbook(List<String> names, [Set<String> hidden = const {}]) {
  final buf = StringBuffer();
  buf.write(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
    'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
    '<sheets>',
  );
  for (var i = 0; i < names.length; i++) {
    final hiddenAttr =
        hidden.contains(names[i]) ? ' state="hidden"' : '';
    buf.write(
      '<sheet name="${_xml(names[i])}" sheetId="${i + 1}" r:id="rId${i + 1}"$hiddenAttr/>',
    );
  }
  buf.write('</sheets></workbook>');
  return buf.toString();
}

String _workbookRels(int sheetCount) {
  final buf = StringBuffer();
  buf.write(
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">',
  );
  for (var i = 1; i <= sheetCount; i++) {
    buf.write(
      '<Relationship Id="rId$i" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet$i.xml"/>',
    );
  }
  buf.write(
    '<Relationship Id="rId${sheetCount + 1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>',
  );
  buf.write('</Relationships>');
  return buf.toString();
}

String _styles() =>
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
    '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
    '<fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="1"><fill><patternFill patternType="none"/></fill></fills>'
    '<borders count="1"><border/></borders>'
    '<cellStyleXfs count="1"><xf/></cellStyleXfs>'
    '<cellXfs count="1"><xf/></cellXfs>'
    '</styleSheet>';
