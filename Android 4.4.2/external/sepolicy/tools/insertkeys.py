#!/usr/bin/env python

from xml.sax import saxutils, handler, make_parser
from optparse import OptionParser
import ConfigParser
import logging
import base64
import sys
import os

__VERSION = (0, 1)

'''
This tool reads a mac_permissions.xml and replaces keywords in the signature
clause with keys provided by pem files.
'''

class GenerateKeys(object):
    def __init__(self, path):
        '''
        Generates an object with Base16 and Base64 encoded versions of the keys
        found in the supplied pem file argument. PEM files can contain multiple
        certs, however this seems to be unused in Android as pkg manager grabs
        the first cert in the APK. This will however support multiple certs in
        the resulting generation with index[0] being the first cert in the pem
        file.
        '''

        self._base64Key = list()
        self._base16Key = list()

        if not os.path.isfile(path):
            sys.exit("Path " + path + " does not exist or is not a file!")

        pkFile = open(path, 'rb').readlines()
        base64Key = ""
        inCert = False
        for line in pkFile:
            if line.startswith("-"):
                inCert = not inCert
                continue

            base64Key += line.strip()

        # Base 64 includes uppercase. DO NOT tolower()
        self._base64Key.append(base64Key)

        # Pkgmanager and setool see hex strings with lowercase, lets be consistent.
        self._base16Key.append(base64.b16encode(base64.b64decode(base64Key)).lower())

    def __len__(self):
        return len(self._base16Key)

    def __str__(self):
        return str(self.getBase16Keys())

    def getBase16Keys(self):
        return self._base16Key

    def getBase64Keys(self):
        return self._base64Key

class ParseConfig(ConfigParser.ConfigParser):

    # This must be lowercase
    OPTION_WILDCARD_TAG = "all"

    def generateKeyMap(self, target_build_variant, key_directory):

        keyMap = dict()

        for tag in self.sections():

            options = self.options(tag)

            for option in options:

                # Only generate the key map for debug or release,
                # not both!
                if option != target_build_variant and \
                option != ParseConfig.OPTION_WILDCARD_TAG:
                    logging.info("Skipping " + tag + " : " + option +
                        " because target build variant is set to " +
                        str(target_build_variant))
                    continue

                if tag in keyMap:
                    sys.exit("Duplicate tag detected " + tag)

                path = os.path.join(key_directory, self.get(tag, option))

                keyMap[tag] = GenerateKeys(path)

                # Multiple certificates may exist in
                # the pem file. GenerateKeys supports
                # this however, the mac_permissions.xml
                # as well as PMS do not.
                assert len(keyMap[tag]) == 1

        return keyMap

class ReplaceTags(handler.ContentHandler):

    DEFAULT_TAG = "default"
    PACKAGE_TAG = "package"
    POLICY_TAG = "policy"
    SIGNER_TAG = "signer"
    SIGNATURE_TAG = "signature"
    CONTENT_TAG = "content"

    TAGS_WITH_CHILDREN = [ DEFAULT_TAG, PACKAGE_TAG, POLICY_TAG, SIGNER_TAG, CONTENT_TAG ]

    XML_ENCODING_TAG = '<?xml version="1.0" encoding="iso-8859-1"?>'

    def __init__(self, keyMap, out=sys.stdout):

        handler.ContentHandler.__init__(self)
        self._keyMap = keyMap
        self._out = out
        self._out.write(ReplaceTags.XML_ENCODING_TAG)
        self._out.write("\n<!-- AUTOGENERATED FILE DO NOT MODIFY -->\n")
        self._out.write("<policy>\n")

    def __del__(self):
        self._out.write("</policy>")

    def startElement(self, tag, attrs):
        if tag == ReplaceTags.POLICY_TAG:
            return

        self._out.write('<' + tag)

        for (name, value) in attrs.items():

            if name == ReplaceTags.SIGNATURE_TAG and value in self._keyMap:
                for key in self._keyMap[value].getBase16Keys():
                    logging.info("Replacing " + name + " " + value + " with " + key)
                    self._out.write(' %s="%s"' % (name, saxutils.escape(key)))
            else:
                self._out.write(' %s="%s"' % (name, saxutils.escape(value)))

        if tag in ReplaceTags.TAGS_WITH_CHILDREN:
            self._out.write('>\r\n')
        else:
            self._out.write('/>\r\n')

    def endElement(self, tag):
        if tag == ReplaceTags.POLICY_TAG:
            return

        if tag in ReplaceTags.TAGS_WITH_CHILDREN:
            self._out.write('</%s>\n' % tag)

    def characters(self, content):
        if not content.isspace():
            self._out.write(saxutils.escape(content))

    def ignorableWhitespace(self, content):
        pass

    def processingInstruction(self, target, data):
        self._out.write('<?%s %s?>' % (target, data))

if __name__ == "__main__":

    # Intentional double space to line up equls signs and opening " for
    # readability.
    usage  = "usage: %prog [options] CONFIG_FILE MAC_PERMISSIONS_FILE [MAC_PERMISSIONS_FILE...]\n"
    usage += "This tool allows one to configure an automatic inclusion\n"
    usage += "of signing keys into the mac_permision.xml file(s) from the\n"
    usage += "pem files. If mulitple mac_permision.xml files are included\n"
    usage += "then they are unioned to produce a final version."

    version = "%prog " + str(__VERSION)

    parser = OptionParser(usage=usage, version=version)

    parser.add_option("-v", "--verbose",
                      action="store_true", dest="verbose", default=False,
                      help="Print internal operations to stdout")

    parser.add_option("-o", "--output", default="stdout", dest="output_file",
                      metavar="FILE", help="Specify an output file, default is stdout")

    parser.add_option("-c", "--cwd", default=os.getcwd(), dest="root",
                      metavar="DIR", help="Specify a root (CWD) directory to run this from, it" \
                                          "chdirs' AFTER loading the config file")

    parser.add_option("-t", "--target-build-variant", default="eng", dest="target_build_variant",
                      help="Specify the TARGET_BUILD_VARIANT, defaults to eng")

    parser.add_option("-d", "--key-directory", default="", dest="key_directory",
                      help="Specify a parent directory for keys")

    (options, args) = parser.parse_args()

    if len(args) < 2:
        parser.error("Must specify a config file (keys.conf) AND mac_permissions.xml file(s)!")

    logging.basicConfig(level=logging.INFO if options.verbose == True else logging.WARN)

    # Read the config file
    config = ParseConfig()
    config.read(args[0])

    os.chdir(options.root)

    output_file = sys.stdout if options.output_file == "stdout" else open(options.output_file, "w")
    logging.info("Setting output file to: " + options.output_file)

    # Generate the key list
    key_map = config.generateKeyMap(options.target_build_variant.lower(), options.key_directory)
    logging.info("Generate key map:")
    for k in key_map:
        logging.info(k + " : " + str(key_map[k]))
    # Generate the XML file with markup replaced with keys
    parser = make_parser()
    parser.setContentHandler(ReplaceTags(key_map, output_file))
    for f in args[1:]:
        parser.parse(f)
