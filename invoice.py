#! -*- coding: utf8 -*-
#This file is part of Tryton.  The COPYRIGHT file at the top level of
#this repository contains the full copyright notices and license terms.

import collections
import logging
from decimal import Decimal
import datetime

from trytond.model import ModelSQL, Workflow, fields, ModelView
from trytond.report import Report
from trytond.pyson import Eval, And, Equal
from trytond.transaction import Transaction
from trytond.pool import Pool, PoolMeta
import base64
import pyqrcode
import io


__all__ = ['Invoice', 'AfipWSTransaction', 'InvoiceReport']
__metaclass__ = PoolMeta

_STATES = {
	'readonly': Eval('state') != 'draft',
}
_DEPENDS = ['state']

_BILLING_STATES = _STATES.copy()
_BILLING_STATES.update({
		'required': (Eval('pyafipws_concept') == '2')
					| (Eval('pyafipws_concept') == '3')
	})

_POS_STATES = _STATES.copy()
_POS_STATES.update({
		'required': And(Eval('type').in_(['out_invoice', 'out_credit_note']), ~Eval('state').in_(['draft'])),
		'invisible': Eval('type').in_(['in_invoice', 'in_credit_note']),
			})

IVA_AFIP_CODE = collections.defaultdict(lambda: 0)
IVA_AFIP_CODE.update({
	Decimal('0'): 3,
	Decimal('0.105'): 4,
	Decimal('0.21'): 5,
	Decimal('0.27'): 6,
	Decimal('0.025'): 9,
	})

INVOICE_TYPE_AFIP_CODE = {
		('out_invoice', 'A'): ('1', u'01-Factura A'),
		('out_invoice', 'B'): ('6', u'06-Factura B'),
		('out_invoice', 'C'): ('11', u'11-Factura C'),
		('out_invoice', 'E'): ('19', u'19-Factura E'),
		('out_credit_note', 'A'): ('3', u'03-Nota de Crédito A'),
		('out_credit_note', 'B'): ('8', u'08-Nota de Crédito B'),
		('out_credit_note', 'C'): ('13', u'13-Nota de Crédito C'),
		('out_credit_note', 'E'): ('21', u'21-Nota de Crédito E'),
		}

INCOTERMS = [
		('', ''),
		('EXW', 'EX WORKS'),
		('FCA', 'FREE CARRIER'),
		('FAS', 'FREE ALONGSIDE SHIP'),
		('FOB', 'FREE ON BOARD'),
		('CFR', 'COST AND FREIGHT'),
		('CIF', 'COST, INSURANCE AND FREIGHT'),
		('CPT', 'CARRIAGE PAID TO'),
		('CIP', 'CARRIAGE AND INSURANCE PAID TO'),
		('DAF', 'DELIVERED AT FRONTIER'),
		('DES', 'DELIVERED EX SHIP'),
		('DEQ', 'DELIVERED EX QUAY'),
		('DDU', 'DELIVERED DUTY UNPAID'),
		('DAT', 'Delivered At Terminal'),
		('DAP', 'Delivered At Place'),
		('DDP', 'Delivered Duty Paid'),
]

TIPO_COMPROBANTE = [
	('', ''),
	('001', 'FACTURAS A'),
	('002', 'NOTAS DE DEBITO A'),
	('003', 'NOTAS DE CREDITO A'),
	('004', 'RECIBOS A'),
	('005', 'NOTAS DE VENTA AL CONTADO A'),
	('006', 'FACTURAS B'),
	('007', 'NOTAS DE DEBITO B'),
	('008', 'NOTAS DE CREDITO B'),
	('009', 'RECIBOS B'),
	('010', 'NOTAS DE VENTA AL CONTADO B'),
	('011', 'FACTURAS C'),
	('012', 'NOTAS DE DEBITO C'),
	('013', 'NOTAS DE CREDITO C'),
	('015', 'RECIBOS C'),
	('016', 'NOTAS DE VENTA AL CONTADO C'),
	('017', 'LIQUIDACION DE SERVICIOS PUBLICOS CLASE A'),
	('018', 'LIQUIDACION DE SERVICIOS PUBLICOS CLASE B'),
	('019', 'FACTURAS DE EXPORTACION'),
	('020', 'NOTAS DE DEBITO POR OPERACIONES CON EL EXTERIOR'),
	('021', 'NOTAS DE CREDITO POR OPERACIONES CON EL EXTERIOR'),
	('022', 'FACTURAS - PERMISO EXPORTACION SIMPLIFICADO - DTO. 855/97'),
	('023', 'COMPROBANTES A DE COMPRA PRIMARIA SECTOR PESQUERO MARITIMO'),
	('024', 'COMPROBANTES A DE CONSIGNACION PRIMARIA SECTOR PESQUERO '
		'MARITIMO'),
	('025', 'COMPROBANTES B DE COMPRA PRIMARIA SECTOR PESQUERO MARITIMO'),
	('026', 'COMPROBANTES B DE CONSIGNACION PRIMARIA SECTOR PESQUERO '
		'MARITIMO'),
	('027', 'LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE A'),
	('028', 'LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE B'),
	('029', 'LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE C'),
	('030', 'COMPROBANTES DE COMPRA DE BIENES USADOS'),
	('031', 'MANDATO - CONSIGNACION'),
	('032', 'COMPROBANTES PARA RECICLAR MATERIALES'),
	('033', 'LIQUIDACION PRIMARIA DE GRANOS'),
	('034', 'COMPROBANTES A DEL APARTADO A INCISO F RG N.1415'),
	('035', 'COMPROBANTES B DEL ANEXO I, APARTADO A, INC. F), RG N. 1415'),
	('036', 'COMPROBANTES C DEL Anexo I, Apartado A, INC.F), R.G. Nro 1415'),
	('037', 'NOTAS DE DEBITO O DOCUMENTO EQUIVALENTE CON LA R.G. Nro 1415'),
	('038', 'NOTAS DE CREDITO O DOCUMENTO EQUIVALENTE CON LA R.G. Nro 1415'),
	('039', 'OTROS COMPROBANTES A QUE CUMPLEN CON LA R G  1415'),
	('040', 'OTROS COMPROBANTES B QUE CUMPLAN CON LA R.G. Nro 1415'),
	('041', 'OTROS COMPROBANTES C QUE CUMPLAN CON LA R.G. Nro 1415'),
	('043', 'NOTA DE CREDITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE B'),
	('044', 'NOTA DE CREDITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE C'),
	('045', 'NOTA DE DEBITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE A'),
	('046', 'NOTA DE DEBITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE B'),
	('047', 'NOTA DE DEBITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE C'),
	('048', 'NOTA DE CREDITO LIQUIDACION UNICA COMERCIAL IMPOSITIVA CLASE A'),
	('049', 'COMPROBANTES DE COMPRA DE BIENES NO REGISTRABLES A CONSUMIDORES '
		'FINALES'),
	('050', 'RECIBO FACTURA A  REGIMEN DE FACTURA DE CREDITO'),
	('051', 'FACTURAS M'),
	('052', 'NOTAS DE DEBITO M'),
	('053', 'NOTAS DE CREDITO M'),
	('054', 'RECIBOS M'),
	('055', 'NOTAS DE VENTA AL CONTADO M'),
	('056', 'COMPROBANTES M DEL ANEXO I  APARTADO A  INC F) R.G. Nro 1415'),
	('057', 'OTROS COMPROBANTES M QUE CUMPLAN CON LA R.G. Nro 1415'),
	('058', 'CUENTAS DE VENTA Y LIQUIDO PRODUCTO M'),
	('059', 'LIQUIDACIONES M'),
	('060', 'CUENTAS DE VENTA Y LIQUIDO PRODUCTO A'),
	('061', 'CUENTAS DE VENTA Y LIQUIDO PRODUCTO B'),
	('063', 'LIQUIDACIONES A'),
	('064', 'LIQUIDACIONES B'),
	('066', 'DESPACHO DE IMPORTACION'),
	('068', 'LIQUIDACION C'),
	('070', 'RECIBOS FACTURA DE CREDITO'),
	('080', 'INFORME DIARIO DE CIERRE (ZETA) - CONTROLADORES FISCALES'),
	('081', 'TIQUE FACTURA A'),
	('082', 'TIQUE FACTURA B'),
	('083', 'TIQUE'),
	('088', 'REMITO ELECTRONICO'),
	('089', 'RESUMEN DE DATOS'),
	('090', 'OTROS COMPROBANTES - DOCUMENTOS EXCEPTUADOS - NOTAS DE CREDITO'),
	('091', 'REMITOS R'),
	('099', 'OTROS COMPROBANTES QUE NO CUMPLEN O ESTAN EXCEPTUADOS DE LA '
		'R.G. 1415 Y SUS MODIF'),
	('110', 'TIQUE NOTA DE CREDITO'),
	('111', 'TIQUE FACTURA C'),
	('112', 'TIQUE NOTA DE CREDITO A'),
	('113', 'TIQUE NOTA DE CREDITO B'),
	('114', 'TIQUE NOTA DE CREDITO C'),
	('115', 'TIQUE NOTA DE DEBITO A'),
	('116', 'TIQUE NOTA DE DEBITO B'),
	('117', 'TIQUE NOTA DE DEBITO C'),
	('118', 'TIQUE FACTURA M'),
	('119', 'TIQUE NOTA DE CREDITO M'),
	('120', 'TIQUE NOTA DE DEBITO M'),
	('331', 'LIQUIDACION SECUNDARIA DE GRANOS'),
	('332', 'CERTIFICACION ELECTRONICA (GRANOS)'),
]


_CREDIT_TYPE = {
	None: None,
	'out_invoice': 'out_credit_note',
	'in_invoice': 'in_credit_note',
	'out_credit_note': 'out_invoice',
	'in_credit_note': 'in_invoice',
	}



class AfipWSTransaction(ModelSQL, ModelView):
	'AFIP WS Transaction'
	__name__ = 'account_invoice_ar.afip_transaction'

	pyafipws_result = fields.Selection([
		   ('', 'n/a'),
		   ('A', 'Aceptado'),
		   ('R', 'Rechazado'),
		   ('O', 'Observado'),
	   ], 'Resultado', readonly=True,
	   help=u"Resultado procesamiento de la Solicitud, devuelto por AFIP")

	pyafipws_message = fields.Text('Mensaje', readonly=True,
	   help=u"Mensaje de error u observación, devuelto por AFIP")
	pyafipws_xml_request = fields.Text('Requerimiento XML', readonly=True,
	   help=u"Mensaje XML enviado a AFIP (depuración)")
	pyafipws_xml_response = fields.Text('Respuesta XML', readonly=True,
	   help=u"Mensaje XML recibido de AFIP (depuración)")

	invoice = fields.Many2One('account.invoice', 'Invoice')


class Invoice:
	'Invoice'
	__name__ = 'account.invoice'

	pos = fields.Many2One('account.pos', 'Point of Sale',
		on_change=['pos', 'party', 'type', 'company'],
		states=_POS_STATES, depends=_DEPENDS)
	invoice_type = fields.Many2One('account.pos.sequence', 'Invoice Type',
		domain=([('pos', '=', Eval('pos'))]),
		states=_POS_STATES, depends=_DEPENDS)

	pyafipws_concept = fields.Selection([
	   ('1', u'1-Productos'),
	   ('2', u'2-Servicios'),
	   ('3', u'3-Productos y Servicios (mercado interno)'),
	   ('4', u'4-Otros (exportación)'),
	   ('', ''),
	   ], 'Concepto',
	   select=True,
	   states={
		   'readonly': Eval('state') != 'draft',
		   'required': Eval('pos.pos_type') == 'electronic',
			}, depends=['state']
	   )
	pyafipws_billing_start_date = fields.Date('Fecha Desde',
	   states=_BILLING_STATES, depends=_DEPENDS,
	   help=u"Seleccionar fecha de fin de servicios - Sólo servicios")
	pyafipws_billing_end_date = fields.Date('Fecha Hasta',
	   states=_BILLING_STATES, depends=_DEPENDS,
	   help=u"Seleccionar fecha de inicio de servicios - Sólo servicios")
	pyafipws_cae = fields.Char('CAE', size=14, readonly=True,
	   help=u"Código de Autorización Electrónico, devuelto por AFIP")
	pyafipws_cae_due_date = fields.Date('Vencimiento CAE', readonly=True,
	   help=u"Fecha tope para verificar CAE, devuelto por AFIP")
	pyafipws_barcode = fields.Char(u'Codigo de Barras', size=40,
		help=u"Código de barras para usar en la impresión", readonly=True,)
	pyafipws_number = fields.Char(u'Número', size=13, readonly=True,
			help=u"Número de factura informado a la AFIP")

	transactions = fields.One2Many('account_invoice_ar.afip_transaction',
								   'invoice', u"Transacciones",
								   readonly=True)
		
	tipo_comprobante = fields.Selection(TIPO_COMPROBANTE, 'Comprobante',
										select=True, depends=['state', 'type'], 
										states={
											'invisible': Eval('type').in_(['out_invoice', 'out_credit_note']),
											'readonly': Eval('state') != 'draft',
											'required': Eval('type').in_(['in_invoice', 'in_credit_note']),
	})

	pyafipws_incoterms = fields.Selection(
		INCOTERMS,
		'Incoterms',
	)

	qr_imagen = fields.Binary(u'Código QR',
									states={
										'invisible': True,
									})
	qr_codigo = fields.Char(u'Información Código QR',
								states={
									'invisible': True,
								})
	qr_texto_modificado = fields.Char(u'Texto codificado Código QR',
								states={
									'invisible': True,
								})

	
	@classmethod
	def default_invoice_type(cls):
		return None


	@classmethod
	def __setup__(cls):
		super(Invoice, cls).__setup__()

		cls._buttons.update({
			'afip_post': {
				'invisible': ~Eval('state').in_(['draft', 'validated']),
				},
			})
		cls._error_messages.update({
			'missing_pyafipws_billing_date':
				u'Debe establecer los valores "Fecha desde" y "Fecha hasta" ' \
				u'en el Diario, correspondientes al servicio que se está facturando',
			'invalid_invoice_number':
				u'El número de la factura (%d), no coincide con el que espera ' \
				u'la AFIP (%d). Modifique la secuencia del diario',
			'not_cae':
				u'No fue posible obtener el CAE. Revise las Transacciones ' \
				u'para mas información',
			'invalid_journal':
				u'Este diario (%s) no tiene establecido los datos necesaios para ' \
				u'facturar electrónicamente',
			'missing_sequence':
				u'No existe una secuencia para facturas del tipo: %s',
			'too_many_sequences':
				u'Existe mas de una secuencia para facturas del tipo: %s',
			'missing_company_iva_condition': ('The iva condition on company '
					'"%(company)s" is missing.'),
			'missing_party_iva_condition': ('The iva condition on party '
					'"%(party)s" is missing.'),
			'not_invoice_type':
				u'El campo «Tipo de factura» en «Factura» es requerido.',
			'change_sale_configuration':
				u'Se debe cambiar la configuracion de la venta para procesar la factura de forma Manual.',
			'missing_pyafipws_incoterms':
				u'Debe establecer el valor de Incoterms si desea realizar un tipo de "Factura E".',
			})

	@classmethod
	@ModelView.button
	@Workflow.transition('validated')
	def validate_invoice(cls, invoices):
		for invoice in invoices:
			if invoice.type in ('out_invoice', 'out_credit_note'):
				invoice.check_invoice_type()
		super(Invoice, cls).validate(invoices)

	@classmethod
	def validate(cls, invoices):
		super(Invoice, cls).validate(invoices)
		for invoice in invoices:
			invoice.check_invoice_type()

	def check_invoice_type(self):
		if not self.company.party.iva_condition:
			self.raise_user_error('missing_company_iva_condition', {
					'company': self.company.rec_name,
					})
		if not self.party.iva_condition:
			self.raise_user_error('missing_party_iva_condition', {
					'party': self.party.rec_name,
					})
		if not self.invoice_type:
			if self.sales:
				self.raise_user_error('change_sale_configuration')
			else:
				if self.type in ('out_invoice', 'out_credit_note'):
					self.raise_user_error('not_invoice_type')

	def on_change_pos(self):
		PosSequence = Pool().get('account.pos.sequence')

		if not self.pos:
			return {'invoice_type': None}

		res = {}
		client_iva = company_iva = None
		if self.party:
			client_iva = self.party.iva_condition
		if self.company:
			company_iva = self.company.party.iva_condition

		if company_iva == 'responsable_inscripto':
			if client_iva is None:
				return res
			if client_iva == 'responsable_inscripto':
				kind = 'A'
			elif client_iva == 'consumidor_final':
				kind = 'B'
			elif self.party.vat_country is None:
				self.raise_user_error('unknown_country')
			elif self.party.vat_country == u'AR':
				kind = 'B'
			else:
				kind = 'E'
		else:
			kind = 'C'

		invoice_type, invoice_type_desc = INVOICE_TYPE_AFIP_CODE[
			(self.type, kind)
			]
		sequences = PosSequence.search([
			('pos', '=', self.pos.id),
			('invoice_type', '=', invoice_type)
			])
		if len(sequences) == 0:
			self.raise_user_error('missing_sequence', invoice_type_desc)
		elif len(sequences) > 1:
			self.raise_user_error('too_many_sequences', invoice_type_desc)
		else:
			res['invoice_type'] = sequences[0].id

		return res

	def set_number(self):
		super(Invoice, self).set_number()

		if self.type == 'out_invoice' or self.type == 'out_credit_note':
			vals = {}
			Sequence = Pool().get('ir.sequence')

			number = Sequence.get_id(self.invoice_type.invoice_sequence.id)
			vals['number'] = '%04d-%08d' % (self.pos.number, int(number))
			self.write([self], vals)

	def _get_move_line(self, date, amount):
		res = super(Invoice, self)._get_move_line(date, amount)

		if self.type[:3] == 'out':
			res['description'] = self.party.name + u' Nro. ' + self.number
		else:
			res['description'] = self.party.name + u' Nro. ' + self.reference

		if self.description:
			res['description'] += ' / ' + self.description

		return res

	@classmethod
	@ModelView.button
	@Workflow.transition('posted')
	def post(cls, invoices):
		Move = Pool().get('account.move')

		moves = []
		for invoice in invoices:
			if invoice.type == u'out_invoice' or invoice.type == u'out_credit_note':
				if not invoice.invoice_type:
					invoice.raise_user_error('not_invoice_type')
				if invoice.pos:
					if invoice.pos.pos_type == 'electronic':
						invoice.do_pyafipws_request_cae()
						
						if not invoice.pyafipws_cae:
							invoice.raise_user_error('not_cae')
			invoice.set_number()
			if invoice.pos.pos_type == 'electronic':
				invoice.crear_codigo_qr()

			moves.append(invoice.create_move())
		cls.write(invoices, {
				'state': 'posted',
				})
		Move.post(moves)
		#Bug: https://github.com/tryton-ar/account_invoice_ar/issues/38
		#for invoice in invoices:
		#    if invoice.type in ('out_invoice', 'out_credit_note'):
		#        invoice.print_invoice()

	def do_pyafipws_request_cae(self):
		logger = logging.getLogger('pyafipws')
		"Request to AFIP the invoices' Authorization Electronic Code (CAE)"
		# if already authorized (electronic invoice with CAE), ignore
		if self.pyafipws_cae:
			logger.info(u'Se trata de obtener CAE de la factura que ya tiene. '\
						u'Factura: %s, CAE: %s', self.number, self.pyafipws_cae)
			return
		# get the electronic invoice type, point of sale and service:
		pool = Pool()

		Company = pool.get('company.company')
		company_id = Transaction().context.get('company')
		if not company_id:
			logger.info(u'No hay companía')
			return

		company = Company(company_id)

		tipo_cbte = self.invoice_type.invoice_type
		punto_vta = self.pos.number
		service = self.pos.pyafipws_electronic_invoice_service
		# check if it is an electronic invoice sale point:
		##TODO
		#if not tipo_cbte:
		#    self.raise_user_error('invalid_sequence', pos.invoice_type.invoice_type)

		# authenticate against AFIP:
		auth_data = company.pyafipws_authenticate(service=service)

		# import the AFIP webservice helper for electronic invoice
		if service == 'wsfe':
			from pyafipws.wsfev1 import WSFEv1  # local market
			ws = WSFEv1()
			if company.pyafipws_mode_cert == 'homologacion':
				WSDL = "https://wswhomo.afip.gov.ar/wsfev1/service.asmx?WSDL"
			elif company.pyafipws_mode_cert == 'produccion':
				WSDL = "https://servicios1.afip.gov.ar/wsfev1/service.asmx?WSDL"
		#elif service == 'wsmtxca':
		#    from pyafipws.wsmtx import WSMTXCA, SoapFault   # local + detail
		#    ws = WSMTXCA()
		elif service == 'wsfex':
			from pyafipws.wsfexv1 import WSFEXv1 # foreign trade
			ws = WSFEXv1()
			if company.pyafipws_mode_cert == 'homologacion':
				WSDL = "https://wswhomo.afip.gov.ar/wsfexv1/service.asmx?WSDL"
			elif company.pyafipws_mode_cert == 'produccion':
				WSDL = "https://servicios1.afip.gov.ar/wsfexv1/service.asmx?WSDL"
		else:
			logger.critical(u'WS no soportado: %s', service)
			return

		# connect to the webservice and call to the test method
		ws.LanzarExcepciones = True
		ws.Conectar(wsdl=WSDL)
		# set AFIP webservice credentials:
		ws.Cuit = company.party.vat_number
		ws.Token = auth_data['token']
		ws.Sign = auth_data['sign']

		# get the last 8 digit of the invoice number
		if self.move:
			cbte_nro = int(self.move.number[-8:])
		else:
			Sequence = pool.get('ir.sequence')
			cbte_nro = int(Sequence(
				self.invoice_type.invoice_sequence.id).get_number_next(''))

		# get the last invoice number registered in AFIP
		if service == "wsfe" or service == "wsmtxca":
			cbte_nro_afip = ws.CompUltimoAutorizado(tipo_cbte, punto_vta)
		elif service == 'wsfex':
			cbte_nro_afip = ws.GetLastCMP(tipo_cbte, punto_vta)
		cbte_nro_next = int(cbte_nro_afip or 0) + 1
		# verify that the invoice is the next one to be registered in AFIP
		#if cbte_nro != cbte_nro_next:
		#	self.raise_user_error('invalid_invoice_number', (cbte_nro, cbte_nro_next))
		###################################################################################################################################################

		# invoice number range (from - to) and date:
		cbte_nro = cbt_desde = cbt_hasta = cbte_nro_next

		if self.invoice_date:
			fecha_cbte = self.invoice_date.strftime("%Y-%m-%d")
		else:
			Date = pool.get('ir.date')
			fecha_cbte = Date.today().strftime("%Y-%m-%d")

		if service != 'wsmtxca':
			fecha_cbte = fecha_cbte.replace("-", "")

		# due and billing dates only for concept "services"
		concepto = tipo_expo = int(self.pyafipws_concept or 0)
		if int(concepto) != 1:

			payments = self.payment_term.compute(self.total_amount, self.currency)
			last_payment = max(payments, key=lambda x:x[0])[0]
			fecha_venc_pago = last_payment.strftime("%Y-%m-%d")
			if service != 'wsmtxca':
					fecha_venc_pago = fecha_venc_pago.replace("-", "")
			if self.pyafipws_billing_start_date:
				fecha_serv_desde = self.pyafipws_billing_start_date.strftime("%Y-%m-%d")
				if service != 'wsmtxca':
					fecha_serv_desde = fecha_serv_desde.replace("-", "")
			else:
				fecha_serv_desde = None
			if  self.pyafipws_billing_end_date:
				fecha_serv_hasta = self.pyafipws_billing_end_date.strftime("%Y-%m-%d")
				if service != 'wsmtxca':
					fecha_serv_hasta = fecha_serv_hasta.replace("-", "")
			else:
				fecha_serv_hasta = None
		else:
			fecha_venc_pago = fecha_serv_desde = fecha_serv_hasta = None

		# customer tax number:
		if self.party.vat_number:
			nro_doc = self.party.vat_number
			if len(nro_doc) < 11:
				tipo_doc = 96           # DNI
			else:
				tipo_doc = 80           # CUIT
		else:
			nro_doc = "0"           # only "consumidor final"
			tipo_doc = 99           # consumidor final

		# invoice amount totals:
		imp_total = str("%.2f" % abs(self.total_amount))
		imp_tot_conc = "0.00"
		imp_neto = str("%.2f" % abs(self.untaxed_amount))
		imp_iva = str("%.2f" % abs(self.tax_amount))
		imp_subtotal = imp_neto  # TODO: not allways the case!
		imp_trib = "0.00"
		imp_op_ex = "0.00"
		if self.currency.code == 'ARS':
			moneda_id = "PES"
			moneda_ctz = 1
		else:
			moneda_id = {'USD':'DOL'}[self.currency.code]
			ctz = 1 / self.currency.rate
			moneda_ctz =  str("%.2f" % ctz)

		# foreign trade data: export permit, country code, etc.:
		if self.pyafipws_incoterms:
			incoterms = self.pyafipws_incoterms
			incoterms_ds = dict(self._fields['pyafipws_incoterms'].selection)[self.pyafipws_incoterms]
		else:
			incoterms = incoterms_ds = None

		if incoterms == None and incoterms_ds == None and service == 'wsfex':
			self.raise_user_error('missing_pyafipws_incoterms')

		if int(tipo_cbte) == 19 and tipo_expo == 1:
			permiso_existente =  "N" or "S"     # not used now
		else:
			permiso_existente = ""
		obs_generales = self.comment
		if self.payment_term:
			forma_pago = self.payment_term.name
			obs_comerciales = self.payment_term.name
		else:
			forma_pago = obs_comerciales = None
		idioma_cbte = 1     # invoice language: spanish / español

		# customer data (foreign trade):
		nombre_cliente = self.party.name
		if self.party.vat_number:
			if self.party.vat_country == "AR":
				# use the Argentina AFIP's global CUIT for the country:
				cuit_pais_cliente = self.party.vat_number
				id_impositivo = None
			else:
				# use the VAT number directly
				id_impositivo = self.party.vat_number
				# TODO: the prefix could be used to map the customer country
				cuit_pais_cliente = None
		else:
			cuit_pais_cliente = id_impositivo = None
		if self.invoice_address:
			address = self.invoice_address
			domicilio_cliente = " - ".join([
										address.name or '',
										address.street or '',
										address.streetbis or '',
										address.zip or '',
										address.city or '',
								])
		else:
			domicilio_cliente = ""
		if self.invoice_address.country:
			# map ISO country code to AFIP destination country code:
			pais_dst_cmp = {
				'ar': 200, 'bo': 202, 'br': 203, 'ca': 204, 'co': 205,
				'cu': 207, 'cl': 208, 'ec': 210, 'us': 212, 'mx': 218,
				'py': 221, 'pe': 222, 'uy': 225, 've': 226, 'cn': 310,
				'tw': 313, 'in': 315, 'il': 319, 'jp': 320, 'at': 405,
				'be': 406, 'dk': 409, 'es': 410, 'fr': 412, 'gr': 413,
				'it': 417, 'nl': 423, 'pt': 620, 'uk': 426, 'sz': 430,
				'de': 438, 'ru': 444, 'eu': 497, 'cr': '206'
				}[self.invoice_address.country.code.lower()]


		# create the invoice internally in the helper
		if service == 'wsfe':
			ws.CrearFactura(concepto, tipo_doc, nro_doc, tipo_cbte, punto_vta,
				cbt_desde, cbt_hasta, imp_total, imp_tot_conc, imp_neto,
				imp_iva, imp_trib, imp_op_ex, fecha_cbte, fecha_venc_pago,
				fecha_serv_desde, fecha_serv_hasta,
				moneda_id, moneda_ctz)
		elif service == 'wsmtxca':
			ws.CrearFactura(concepto, tipo_doc, nro_doc, tipo_cbte, punto_vta,
				cbt_desde, cbt_hasta, imp_total, imp_tot_conc, imp_neto,
				imp_subtotal, imp_trib, imp_op_ex, fecha_cbte,
				fecha_venc_pago, fecha_serv_desde, fecha_serv_hasta,
				moneda_id, moneda_ctz, obs_generales)
		elif service == 'wsfex':
			ws.CrearFactura(tipo_cbte, punto_vta, cbte_nro, fecha_cbte,
				imp_total, tipo_expo, permiso_existente, pais_dst_cmp,
				nombre_cliente, cuit_pais_cliente, domicilio_cliente,
				id_impositivo, moneda_id, moneda_ctz, obs_comerciales,
				obs_generales, forma_pago, incoterms,
				idioma_cbte, incoterms_ds)

		# analyze VAT (IVA) and other taxes (tributo):
		if service in ('wsfe', 'wsmtxca'):
			for tax_line in self.taxes:
				tax = tax_line.tax
				if tax.group.name == "IVA":
					iva_id = IVA_AFIP_CODE[tax.rate]
					base_imp = ("%.2f" % abs(tax_line.base))
					importe = ("%.2f" % abs(tax_line.amount))
					# add the vat detail in the helper
					ws.AgregarIva(iva_id, base_imp, importe)
				else:
					if 'impuesto' in tax_line.tax.name.lower():
						tributo_id = 1  # nacional
					elif 'iibbb' in tax_line.tax.name.lower():
						tributo_id = 3  # provincial
					elif 'tasa' in tax_line.tax.name.lower():
						tributo_id = 4  # municipal
					else:
						tributo_id = 99
					desc = tax_line.name
					base_imp = ("%.2f" % abs(tax_line.base))
					importe = ("%.2f" % abs(tax_line.amount))
					alic = "%.2f" % tax_line.base
					# add the other tax detail in the helper
					ws.AgregarTributo(tributo_id, desc, base_imp, alic, importe)

				## Agrego un item:
				#codigo = "PRO1"
				#ds = "Producto Tipo 1 Exportacion MERCOSUR ISO 9001"
				#qty = 2
				#precio = "150.00"
				#umed = 1 # Ver tabla de parámetros (unidades de medida)
				#bonif = "50.00"
				#imp_total = "250.00" # importe total final del artículo
		# analize line items - invoice detail
		# umeds
		# Parametros. Unidades de Medida, etc.
		# https://code.google.com/p/pyafipws/wiki/WSFEX#WSFEX/RECEX_Parameter_Tables
		if service in ('wsfex', 'wsmtxca'):
			for line in self.lines:
				if line.product:
					codigo = line.product.code
				else:
					codigo = 0
				ds = line.description
				qty = line.quantity
				umed = 7 # FIXME: (7 - unit)
				precio = str(line.unit_price)
				importe_total = str(line.amount)
				bonif = None  # line.discount
				#for tax in line.taxes:
				#    if tax.group.name == "IVA":
				#        iva_id = IVA_AFIP_CODE[tax.rate]
				#        imp_iva = importe * tax.rate
				#if service == 'wsmtxca':
				#    ws.AgregarItem(u_mtx, cod_mtx, codigo, ds, qty, umed,
				#            precio, bonif, iva_id, imp_iva, importe+imp_iva)
				if service == 'wsfex':
					ws.AgregarItem(codigo, ds, qty, umed, precio, importe_total,
								   bonif)

		# Request the authorization! (call the AFIP webservice method)
		try:
			if service == 'wsfe':
				ws.CAESolicitar()
				vto = ws.Vencimiento
			elif service == 'wsmtxca':
				ws.AutorizarComprobante()
				vto = ws.Vencimiento
			elif service == 'wsfex':
				ws.Authorize(self.id)
				vto = ws.FchVencCAE
		#except SoapFault as fault:
		#    msg = 'Falla SOAP %s: %s' % (fault.faultcode, fault.faultstring)
		except Exception, e:
			if ws.Excepcion:
				# get the exception already parsed by the helper
				#import ipdb; ipdb.set_trace()  # XXX BREAKPOINT
				msg = ws.Excepcion + ' ' + str(e)
			else:
				# avoid encoding problem when reporting exceptions to the user:
				import traceback
				import sys
				msg = traceback.format_exception_only(sys.exc_type,
													  sys.exc_value)[0]
		else:
			msg = u"\n".join([ws.Obs or "", ws.ErrMsg or ""])
		# calculate the barcode:
		if ws.CAE:
			cae_due = ''.join([c for c in str(ws.Vencimiento or '')
									   if c.isdigit()])
			bars = ''.join([str(ws.Cuit), "%02d" % int(tipo_cbte),
							  "%04d" % int(punto_vta),
							  str(ws.CAE), cae_due])
			bars = bars + self.pyafipws_verification_digit_modulo10(bars)
		else:
			bars = ""

		AFIP_Transaction = pool.get('account_invoice_ar.afip_transaction')
		with Transaction().new_cursor():
			AFIP_Transaction.create([{'invoice': self,
								'pyafipws_result': ws.Resultado,
								'pyafipws_message': msg,
								'pyafipws_xml_request': ws.XmlRequest,
								'pyafipws_xml_response': ws.XmlResponse,
								}])
			Transaction().cursor.commit()

		if ws.CAE:

			# store the results
			vals = {'pyafipws_cae': ws.CAE,
				   'pyafipws_cae_due_date': vto or None,
				   'pyafipws_barcode': bars,
				}
			if not '-' in vals['pyafipws_cae_due_date']:
				fe = vals['pyafipws_cae_due_date']
				vals['pyafipws_cae_due_date'] = '-'.join([fe[:4],fe[4:6],fe[6:8]])

			self.write([self], vals)


	def pyafipws_verification_digit_modulo10(self, codigo):
		"Calculate the verification digit 'modulo 10'"
		# http://www.consejo.org.ar/Bib_elect/diciembre04_CT/documentos/rafip1702.htm
		# Step 1: sum all digits in odd positions, left to right
		codigo = codigo.strip()
		if not codigo or not codigo.isdigit():
			return ''
		etapa1 = sum([int(c) for i,c in enumerate(codigo) if not i%2])
		# Step 2: multiply the step 1 sum by 3
		etapa2 = etapa1 * 3
		# Step 3: start from the left, sum all the digits in even positions
		etapa3 = sum([int(c) for i,c in enumerate(codigo) if i%2])
		# Step 4: sum the results of step 2 and 3
		etapa4 = etapa2 + etapa3
		# Step 5: the minimun value that summed to step 4 is a multiple of 10
		digito = 10 - (etapa4 - (int(etapa4 / 10) * 10))
		if digito == 10:
			digito = 0
		return str(digito)


	
	def crear_codigo_qr(self):
		######################################################################################################################
		#
		# GENERACION DE CODIGO QR PARA FACTURAS ELECTRONICAS SEGUN RESOLUCCION AFIP
		#
		######################################################################################################################
		# si el POS es tipo electronico genero el codigo QR
		if self.pos.pos_type == 'electronic':
			if self.party.iva_condition == 'consumidor_final':
				nro_doc = self.party.vat_number
				if len(str(nro_doc).strip()) > 5:
					tipo_doc = 96
				else:
					nro_doc = '0'
					tipo_doc = 99
			elif (self.party.iva_condition == 'responsable_inscripto'):
				if self.party.vat_number:
					nro_doc = self.party.vat_number
					if len(str(nro_doc).strip()) < 11:
						tipo_doc = 96  # DNI
					else:
						tipo_doc = 80  # CUIT
			elif self.party.iva_condition == 'monotributo':
				if self.party.vat_number:
					nro_doc = self.party.vat_number
					if len(str(nro_doc).strip()) < 11:
						tipo_doc = 96  # DNI
					else:
						tipo_doc = 80  # CUIT
			elif self.party.iva_condition == 'exento':
				if self.party.vat_number:
					nro_doc = self.party.vat_number
					if len(str(nro_doc).strip()) < 11:
						tipo_doc = 96  # DNI
					else:
						tipo_doc = 80  # CUIT
			else:
				if self.party.vat_number:
					nro_doc = self.party.vat_number
					if len(str(nro_doc).strip()) > 0:
						tipo_doc = 96  # DNI
					else:
						tipo_doc = 99  # NO DEFINIDO
			
			vals = {}
			dict_invoice = {
				'ver': 1,
				'fecha': str(self.invoice_date),
				'cuit': int(self.company.party.vat_number),
				'ptoVta': self.pos.number,
				'tipoCmp': int(self.invoice_type.invoice_type),
				'nroCmp': int(self.number.split('-')[1]),
				'importe': self.total_amount,
				'moneda': 'PES',
				'ctz': 1,
				'tipoDocRec': int(tipo_doc),
				'nroDocRec': int(nro_doc),
				'tipoCodAut': 'E',
				'codAut': self.pyafipws_cae,
			}
			res = str(dict_invoice).replace("\n", "")
			vals['qr_codigo'] = res

			if type(dict_invoice) == dict:
				enc = res.encode()
				b64 = base64.encodestring(enc)
				string_qr = 'https://www.afip.gob.ar/fe/qr/?p=' + str(b64)
			else:
				string_qr = 'https://www.afip.gob.ar/fe/qr/?ERROR'
			vals['qr_texto_modificado'] = string_qr		
		
			url = pyqrcode.create(string_qr, error='L', version=13, mode='binary')
			with open('code.png', 'w') as fstream:
				url.png(fstream, scale=1)
				buffer = io.BytesIO()
				url.png(buffer)
				vals['qr_imagen'] = buffer.getvalue()
		
		
			self.write([self], vals)
		return True



	@classmethod
	def credit(cls, invoices, refund=False):
		'''
		Credit invoices and return ids of new invoices.
		Return the list of new invoice
		'''

		MoveLine = Pool().get('account.move.line')
		AccountPosSequence = Pool().get('account.pos.sequence')

		new_invoices = []
		for invoice in invoices:
			new_invoice, = cls.create([invoice._credit()])

			# Agrego Invoice Type de NC facturas comunes
			if invoice.invoice_type.invoice_type == '1':  # Factura A
				account_pos_sequence = AccountPosSequence.search([
				('invoice_type', '=', '3'),
				('pos', '=', invoice.invoice_type.pos),
				])
			elif invoice.invoice_type.invoice_type == '6':
				account_pos_sequence = AccountPosSequence.search([
				('invoice_type', '=', '8'),
				('pos', '=', invoice.invoice_type.pos),
				])

			new_invoice.invoice_type = account_pos_sequence[0]
			new_invoice.invoice_date = datetime.date.today()
			new_invoice.pyafipws_concept = invoice.pyafipws_concept
			new_invoice.pyafipws_billing_start_date = invoice.pyafipws_billing_start_date
			new_invoice.pyafipws_billing_end_date = invoice.pyafipws_billing_end_date

			new_invoice.save()

			Transaction().cursor.commit()

			new_invoices.append(new_invoice)
			if refund:
				cls.post([new_invoice])
				if new_invoice.state == 'posted':
					MoveLine.reconcile([l for l in invoice.lines_to_pay
										if not l.reconciliation] +
									   [l for l in new_invoice.lines_to_pay
										if not l.reconciliation])
		cls.update_taxes(new_invoices)
		return new_invoices

	def _credit(self):
		'''
		Return values to credit invoice.
		'''

		res = {}
		res['type'] = _CREDIT_TYPE[self.type]

		for field in ('description', 'comment','invoice_date', 'pos', 'invoice_type'):
			res[field] = getattr(self, field)

		for field in ('company', 'party', 'invoice_address', 'currency',
				'journal', 'account', 'payment_term'):
			res[field] = getattr(self, field).id

		res['lines'] = []
		if self.lines:
			res['lines'].append(('create',
					[line._credit() for line in self.lines]))

		res['taxes'] = []
		to_create = [tax._credit() for tax in self.taxes if tax.manual]
		if to_create:
			res['taxes'].append(('create', to_create))
		return res



class InvoiceReport(Report):
	__name__ = 'account.invoice'

	@classmethod
	def parse(cls, report, records, data, localcontext):
		pool = Pool()
		User = pool.get('res.user')
		Invoice = pool.get('account.invoice')

		invoice = records[0]

		user = User(Transaction().user)
		localcontext['company'] = user.company
		localcontext['barcode_img'] = cls._get_pyafipws_barcode_img(Invoice, invoice)
		localcontext['condicion_iva'] = cls._get_condicion_iva(user.company)
		localcontext['iibb_type'] = cls._get_iibb_type(user.company)
		localcontext['vat_number'] = cls._get_vat_number(user.company)
		localcontext['tipo_comprobante'] = cls._get_tipo_comprobante(Invoice, invoice)
		localcontext['nombre_comprobante'] = cls._get_nombre_comprobante(Invoice, invoice)
		localcontext['codigo_comprobante'] = cls._get_codigo_comprobante(Invoice, invoice)
		localcontext['condicion_iva_cliente'] = cls._get_condicion_iva_cliente(Invoice, invoice)
		localcontext['vat_number_cliente'] = cls._get_vat_number_cliente(Invoice, invoice)
		localcontext['invoice_impuestos'] = cls._get_invoice_impuestos(Invoice, invoice)
		localcontext['show_tax'] = cls._show_tax(Invoice, invoice)
		localcontext['get_line_amount'] = cls.get_line_amount
		return super(InvoiceReport, cls).parse(report, records, data,
				localcontext=localcontext)

	@classmethod
	def get_line_amount(self,tipo_comprobante, line_amount, line_taxes):
		total = line_amount
		if tipo_comprobante != 'A':
			for tax in line_taxes:
				if tax.tax.rate:
					total = total + (line_amount * tax.tax.rate)
				elif tax.tax.amount:
					total = total + tax.tax.amount
		return total

	@classmethod
	def _show_tax(cls, Invoice, invoice):
		tipo_comprobante = cls._get_tipo_comprobante(Invoice, invoice)
		if tipo_comprobante == 'A':
			return True
		else:
			return False

	@classmethod
	def _get_invoice_impuestos(cls, Invoice, invoice):
		tipo_comprobante = cls._get_tipo_comprobante(Invoice, invoice)
		if tipo_comprobante == 'A':
			return invoice.tax_amount
		else:
			return Decimal('00.00')

	@classmethod
	def _get_condicion_iva_cliente(cls, Invoice, invoice):
		return dict(invoice.party._fields['iva_condition'].selection)[invoice.party.iva_condition]

	@classmethod
	def _get_vat_number_cliente(cls, Invoice, invoice):
		value = invoice.party.vat_number
		if value:
			return '%s-%s-%s' % (value[:2], value[2:-1], value[-1])
		return ''

	@classmethod
	def _get_tipo_comprobante(cls, Invoice, invoice):
		if hasattr(invoice.invoice_type, 'invoice_type') == True:
			return dict(invoice.invoice_type._fields['invoice_type'].selection)[invoice.invoice_type.invoice_type][-1]
		else:
		   return ''

	@classmethod
	def _get_nombre_comprobante(cls, Invoice, invoice):
		if hasattr(invoice.invoice_type, 'invoice_type') == True:
			return dict(invoice.invoice_type._fields['invoice_type'].selection)[invoice.invoice_type.invoice_type][3:-2]
		else:
		   return ''

	@classmethod
	def _get_codigo_comprobante(cls, Invoice, invoice):
		if hasattr(invoice.invoice_type, 'invoice_type') == True:
			return dict(invoice.invoice_type._fields['invoice_type'].selection)[invoice.invoice_type.invoice_type][:2]
		else:
		   return ''

	@classmethod
	def _get_vat_number(cls, company):
		value = company.party.vat_number
		return '%s-%s-%s' % (value[:2], value[2:-1], value[-1])

	@classmethod
	def _get_condicion_iva(cls, company):
		return dict(company.party._fields['iva_condition'].selection)[company.party.iva_condition]

	@classmethod
	def _get_iibb_type(cls, company):
		return company.party.iibb_type.upper()+' '+company.party.iibb_number

	@classmethod
	def _get_pyafipws_barcode_img(cls, Invoice, invoice):
		"Generate the required barcode Interleaved of 7 image using PIL"
		from pyafipws.pyi25 import PyI25
		from cStringIO import StringIO as StringIO
		# create the helper:
		pyi25 = PyI25()
		output = StringIO()
		if not invoice.pyafipws_barcode:
			return
		# call the helper:
		bars = ''.join([c for c in invoice.pyafipws_barcode if c.isdigit()])
		if not bars:
			bars = "00"
		pyi25.GenerarImagen(bars, output, basewidth=3, width=380, height=50, extension="PNG")
		image = buffer(output.getvalue())
		output.close()
		return image