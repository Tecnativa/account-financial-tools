# -*- coding: utf-8 -*-
# Copyright 2004-2010 Tiny SPRL (<http://tiny.be>)
# Copyright 2007 Tecnativa - Vicent Cubells
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import datetime
import time

from openerp import api, fields, models, _


class AccountFollowupSendingResults(models.TransientModel):
    _name = 'account_followup.sending.results'
    _description = 'Results from the sending of the different letters and ' \
                   'emails'

    @api.multi
    def do_report(self):
        return self.env.context.get('report_data')

    @api.multi
    def do_done(self):
        return {}

    @api.multi
    def _get_description(self):
        return self.env.context.get('description')

    @api.multi
    def _get_need_printing(self):
        return self.env.context.get('needprinting')

    description = fields.Text(
        string="Description",
        compute='_get_description',
    )
    needprinting = fields.Boolean(
        string="Needs Printing",
        compute='_get_need_printing',
    )


class AccountFollowupPrint(models.TransientModel):
    _name = 'account_followup.print'
    _description = 'Print Follow-up & Send Mail to Customers'

    def _get_followup(self):
        if self.env.context.get('active_model') == 'account_followup.followup':
            return self.env.context.get('active_id', False)
        company_id = self.env.user.company_id.id
        followup_id = self.env['account_followup.followup'].search([
            ('company_id', '=', company_id)
        ])
        return followup_id.id

    date = fields.Date(
        string='Follow-up Sending Date',
        required=True,
        default=fields.Date.context_today,
        help="This field allow you to select a forecast date to plan your "
             "follow-ups",
    )
    followup_id = fields.Many2one(
        comodel_name='account_followup.followup',
        string='Follow-Up',
        required=True,
        readonly=True,
        default=_get_followup,
    )
    partner_ids = fields.Many2many(
        comodel_name='account_followup.stat.by.partner',
        relation='partner_stat_rel',
        column1='osv_memory_id',
        column2='partner_id',
        string='Partners',
        required=True,
    )
    company_id = fields.Many2one(
        related='followup_id.company_id',
        relation='res.company',
        store=True,
        readonly=True,
    )
    email_conf = fields.Boolean(
        string='Send Email Confirmation',
    )
    email_subject = fields.Char(
        default=_('Invoices Reminder'),
    )
    partner_lang = fields.Boolean(
        string='Send Email in Partner Language',
        default=True,
        help='Do not change message text, if you want to send email in '
             'partner language, or configure from company',
    )
    email_body = fields.Text(
        default='',
    )
    summary = fields.Text(
        readonly=True,
    )
    test_print = fields.Boolean(
        help='Check if you want to print follow-ups without changing '
             'follow-up level.',
    )

    @api.multi
    def process_partners(self, partner_ids, data):
        partner_obj = self.env['res.partner']
        partner_ids_to_print = []
        nbmanuals = 0
        manuals = {}
        nbmails = 0
        nbunknownmails = 0
        nbprints = 0
        resulttext = " "
        for partner in self.env['account_followup.stat.by.partner'].browse(
                partner_ids):
            if partner.max_followup_id.manual_action:
                partner_obj.do_partner_manual_action([partner.partner_id.id])
                nbmanuals += 1
                key = partner.partner_id.payment_responsible_id.name or _(
                    "Anybody")
                if key not in manuals.keys():
                    manuals[key] = 1
                else:
                    manuals[key] += 1
            if partner.max_followup_id.send_email:
                nbunknownmails += partner.partner_id.do_partner_mail()
                nbmails += 1
            if partner.max_followup_id.send_letter:
                partner_ids_to_print.append(partner.id)
                nbprints += 1
                message = "%s<I> %s </I>%s" % (
                    _("Follow-up letter of "),
                    partner.partner_id
                    .latest_followup_level_id_without_lit.name,
                    _(" will be sent")
                )
                partner_obj.message_post([partner.partner_id.id], body=message)
        if nbunknownmails == 0:
            resulttext += str(nbmails) + _(" email(s) sent")
        else:
            resulttext += str(nbmails) + \
                _(" email(s) should have been sent, but ") + \
                str(nbunknownmails) + \
                _(" had unknown email address(es)") + \
                "\n <BR/> "
        resulttext += "<BR/>" + str(nbprints) + \
                      _(" letter(s) in report") + \
                      " \n <BR/>" + str(nbmanuals) + \
                      _(" manual action(s) assigned:")
        needprinting = False
        if nbprints > 0:
            needprinting = True
        resulttext += "<p align=\"center\">"
        for item in manuals:
            resulttext = resulttext + \
                "<li>" + item + \
                ":" + \
                str(manuals[item]) + \
                "\n </li>"
        resulttext += "</p>"
        result = {}
        action = partner_obj.do_partner_print(partner_ids_to_print, data)
        result['needprinting'] = needprinting
        result['resulttext'] = resulttext
        result['action'] = action or {}
        return result

    @api.multi
    def do_update_followup_level(self, to_update, partner_list, date):
        # update the follow-up level on account.move.line
        for id in to_update.keys():
            if to_update[id]['partner_id'] in partner_list:
                for aml in self.env['account.move.line'].browse([int(id)]):
                    aml.write({
                        'followup_line_id': to_update[id]['level'],
                        'followup_date': date
                    })

    @api.multi
    def clear_manual_actions(self, partner_list):
        # Partnerlist is list to exclude
        # Will clear the actions of partners that have no due payments anymore
        partner_list_ids = [
            partner.partner_id.id for partner in
            self.env['account_followup.stat.by.partner'].browse(partner_list)
        ]
        ids = self.env['res.partner'].search([
            '&', ('id', 'not in', partner_list_ids), '|',
            ('payment_responsible_id', '!=', False),
            ('payment_next_action_date', '!=', False)
        ])

        partners_to_clear = []
        for part in self.env['res.partner'].browse(ids):
            if not part.unreconciled_aml_ids:
                partners_to_clear.append(part.id)
        self.env['res.partner'].action_done(partners_to_clear)
        return len(partners_to_clear)

    @api.multi
    def do_process(self):
        self.ensure_one()
        # Get partners
        tmp = self._get_partners_followup()
        partner_list = tmp['partner_ids']
        to_update = tmp['to_update']
        for afp in self:
            date = afp.date
            # Update partners
            afp.do_update_followup_level(to_update, partner_list, date)
            # process the partners (send mails...)
            restot_context = self.env.context.copy()
            restot = self.with_context(restot_context).process_partners(
                partner_list, afp)
            # clear the manual actions if nothing is due anymore
            nbactionscleared = self.clear_manual_actions(partner_list)
            if nbactionscleared > 0:
                restot['resulttext'] += \
                    "<li>" + \
                    _("%s partners have no credits and as such the action is "
                        "cleared") % (str(nbactionscleared)) + "</li>"
            # return the next action
            mod_obj = self.env['ir.model.data']
            model_data_ids = mod_obj.search([
                ('model', '=', 'ir.ui.view'),
                ('name', '=', 'view_account_followup_sending_results')
            ])
            resource_id = mod_obj.read(
                model_data_ids, fields=['res_id'])[0]['res_id']
            restot_context.update({
                'description': restot['resulttext'],
                'needprinting': restot['needprinting'],
                'report_data': restot['action']
            })
            return {
                'name': _('Send Letters and Emails: Actions Summary'),
                'view_type': 'form',
                'context': restot_context,
                'view_mode': 'tree,form',
                'res_model': 'account_followup.sending.results',
                'views': [(resource_id, 'form')],
                'type': 'ir.actions.act_window',
                'target': 'new',
                }

    @api.multi
    def _get_msg(self):
        return self.env.user.company_id.follow_up_msg

    @api.multi
    def _get_partners_followup(self):
        for data in self:
            self.env.cr.execute(
                # l.blocked added to take litigation into account and it is not
                # necessary to change follow-up level of account move lines
                # without debit
                "SELECT l.partner_id, l.followup_line_id,l.date_maturity, "
                "l.date, l.id "
                "FROM account_move_line AS l "
                "LEFT JOIN account_account AS a "
                "ON (l.account_id=a.id) "
                "WHERE (l.reconciled IS False) "
                "AND (l.partner_id is NOT NULL) "
                "AND (l.debit > 0) "
                "AND (l.company_id = %s) "
                "AND (l.blocked = False)"
                "ORDER BY l.date", (data.company_id.id,))
            move_lines = self.env.cr.fetchall()
            old = None
            fups = {}
            fup_id = 'followup_id' in self.env.context and \
                     self.env.context['followup_id'] or data.followup_id.id
            date = 'date' in self.env.context and \
                   self.env.context['date'] or data.date

            current_date = datetime.date(*time.strptime(date, '%Y-%m-%d')[:3])
            self.env.cr.execute(
                "SELECT * "
                "FROM account_followup_followup_line "
                "WHERE followup_id=%s "
                "ORDER BY delay", (fup_id.id,))

            # Create dictionary of tuples where first element is the date to
            # compare with the due date and second element is the id of the
            # next level
            for result in self.env.cr.dictfetchall():
                delay = datetime.timedelta(days=result['delay'])
                fups[old] = (current_date - delay, result['id'])
                old = result['id']

            partner_list = []
            to_update = {}

            # Fill dictionary of accountmovelines to_update with the partners
            # that need to be updated
            for partner_id, followup_line_id, date_maturity, date, id in \
                    move_lines:
                if not partner_id:
                    continue
                if followup_line_id not in fups:
                    continue
                stat_line_id = partner_id * 10000 + data.company_id.id
                if date_maturity:
                    if date_maturity <= fups[followup_line_id][0].\
                            strftime('%Y-%m-%d'):
                        if stat_line_id not in partner_list:
                            partner_list.append(stat_line_id)
                        to_update[str(id)] = {
                            'level': fups[followup_line_id][1],
                            'partner_id': stat_line_id
                        }
                elif date and date <= fups[followup_line_id][0].\
                        strftime('%Y-%m-%d'):
                    if stat_line_id not in partner_list:
                        partner_list.append(stat_line_id)
                    to_update[str(id)] = {
                        'level': fups[followup_line_id][1],
                        'partner_id': stat_line_id}
        return {'partner_ids': partner_list, 'to_update': to_update}
