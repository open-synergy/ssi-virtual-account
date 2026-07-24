.. image:: https://img.shields.io/badge/licence-AGPL--3-blue.svg
   :target: http://www.gnu.org/licenses/agpl-3.0-standalone.html
   :alt: License: AGPL-3

===================
Nicepay Integration
===================

Integrates Nicepay Virtual Account (VA) payment notifications with Odoo.
Every VA notification received is stored under *Settings > Technical >
Nicepay* together with its processing status, so the original payload is
never lost even if processing fails; failed notifications can be
reprocessed manually from there once the underlying issue is fixed.

Settlement records pulled from Nicepay's Settlement History report API are
stored the same way under *Settings > Technical > Nicepay* for
bookkeeping/reconciliation reference; importing them is done by an
on-site job outside this module.


Installation
============

To install this module, you need to:

1.  Clone the branch 14.0 of the repository https://github.com/open-synergy/ssi-virtual-account
2.  Add the path to this repository in your configuration (addons-path)
3.  Update the module list
4.  Go to menu *Apps -> Apps -> Main Apps*
5.  Search For *Nicepay Integration*
6.  Install the module

Bug Tracker
===========

Bugs are tracked on `GitHub Issues
<https://github.com/open-synergy/ssi-virtual-account/issues>`_.
In case of trouble, please check there if your issue has already been reported.
If you spotted it first, help us smashing it by providing a detailed
and welcomed feedback.


Credits
=======

Contributors
------------

* Michael Viriyananda <viriyananda.michael@gmail.com>

Maintainer
----------

.. image:: https://simetri-sinergi.id/logo.png
   :alt: PT. Simetri Sinergi Indonesia
   :target: https://simetri-sinergi.id

This module is maintained by the PT. Simetri Sinergi Indonesia.
