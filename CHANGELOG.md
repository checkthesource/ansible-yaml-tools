# checkthesource\.yaml\_tools Release Notes

**Topics**

- <a href="#v1-1-0">v1\.1\.0</a>
    - <a href="#release-summary">Release Summary</a>
    - <a href="#minor-changes">Minor Changes</a>
    - <a href="#bugfixes">Bugfixes</a>
    - <a href="#new-modules">New Modules</a>
- <a href="#v1-0-1">v1\.0\.1</a>
    - <a href="#release-summary-1">Release Summary</a>
- <a href="#v1-0-0">v1\.0\.0</a>
    - <a href="#release-summary-2">Release Summary</a>
    - <a href="#new-modules-1">New Modules</a>

<a id="v1-1-0"></a>
## v1\.1\.0

<a id="release-summary"></a>
### Release Summary

Select list items and documents by their content\, rename keys\, merge
dictionaries with the new <code>yaml\_merge</code> module and read values with the new
<code>yaml\_info</code> module\. Templated numbers are now written as numbers\.

<a id="minor-changes"></a>
### Minor Changes

* document \- the <code>document</code> option of every module accepts a dictionary of fields\, such as <code>\{kind\: Deployment\, metadata\.name\: web\}</code>\, that must match a single document of a multi\-document file\.
* key paths \- select a list item by the value of one or more of its fields\, for example <code>users\[name\=alice\]\.shell</code> or <code>containers\[name\=web\,image\=\"nginx\:1\.27\"\]</code>\, in every module\. In the list form of <code>key</code>\, a dictionary is a selector\.
* yaml\_edit \- add the <code>rename\_to</code> option\, also available in <code>edits</code>\, to rename a key while keeping its value\, its comments and its position\.
* yaml\_edit\, yaml\_list\, yaml\_merge \- add the <code>infer\_types</code> option \(default <code>true</code>\)\, which writes strings that are plainly integers or booleans as integers and booleans\.

<a id="bugfixes"></a>
### Bugfixes

* yaml\_edit\, yaml\_list \- before ansible\-core 2\.19\, templated numbers such as <code>\"\{\{ port \}\}\"</code> reach modules as strings\, even with <code>\| int</code>\. They were written as quoted strings \(<code>\'8080\'</code>\)\, and <code>yaml\_list</code> did not recognise them as equal to existing numbers\, so it added duplicate items\. They are now written as numbers\. Set <code>infer\_types</code> to <code>false</code> to keep the previous behaviour\.

<a id="new-modules"></a>
### New Modules

* checkthesource\.yaml\_tools\.yaml\_info \- Read a value from a YAML file on the managed node\.
* checkthesource\.yaml\_tools\.yaml\_merge \- Merge a dictionary into a YAML file without reformatting it\.

<a id="v1-0-1"></a>
## v1\.0\.1

<a id="release-summary-1"></a>
### Release Summary

First release published on Ansible Galaxy\. Version 1\.0\.0 was tagged on GitHub
but never published\, because of a problem in the release workflow\.

<a id="v1-0-0"></a>
## v1\.0\.0

<a id="release-summary-2"></a>
### Release Summary

First release of the <code>checkthesource\.yaml\_tools</code> collection\: edit YAML files from
Ansible without reformatting them\. Every edit is lossless whenever possible
and is verified before the file is written\.

<a id="new-modules-1"></a>
### New Modules

* checkthesource\.yaml\_tools\.yaml\_edit \- Set or remove values in a YAML file without reformatting it\.
* checkthesource\.yaml\_tools\.yaml\_list \- Add\, update or remove items of a list in a YAML file without reformatting it\.
